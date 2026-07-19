from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode

import websockets

from app.dhan_client import DhanClient
from app.matsya.db import connect, run_schema
from app.matsya.intraday_paper import (
    DhanTickerPacketCodec,
    IntradayPaperEngine,
    MarketTick,
    SubscriptionTarget,
    subscription_messages,
)
from app.matsya.ohlcv_service import INSTRUMENT_LATERAL_JOIN_SQL
from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import DhanLiveMarketCredentials, MatsyaDhanTokenService
from app.timezone import IST


class FeedClient(Protocol):
    async def stream(
        self,
        credentials: DhanLiveMarketCredentials,
        target_provider: Callable[[], list[SubscriptionTarget]],
    ) -> AsyncIterator[bytes]: ...


class DhanV2WebSocketFeedClient:
    def __init__(self, settings: MatsyaSettings) -> None:
        self.settings = settings

    async def stream(
        self,
        credentials: DhanLiveMarketCredentials,
        target_provider: Callable[[], list[SubscriptionTarget]],
    ) -> AsyncIterator[bytes]:
        query = urlencode(
            {
                "version": "2",
                "token": credentials.access_token,
                "clientId": credentials.dhan_client_id,
                "authType": "2",
            }
        )
        url = f"{self.settings.dhan_live_feed_url.rstrip('/')}?{query}"
        async with websockets.connect(url, ping_interval=10, ping_timeout=40, close_timeout=10) as socket:
            subscribed: set[tuple[str, str]] = set()
            last_packet_at = asyncio.get_running_loop().time()
            while True:
                desired_targets = target_provider()
                desired = {(target.exchange_segment, target.security_id) for target in desired_targets}
                added = [SubscriptionTarget("", security_id, segment) for segment, security_id in desired - subscribed]
                removed = [SubscriptionTarget("", security_id, segment) for segment, security_id in subscribed - desired]
                for message in subscription_messages(added, request_code=15):
                    await socket.send(message)
                for message in subscription_messages(removed, request_code=16):
                    await socket.send(message)
                subscribed = desired
                try:
                    packet = await asyncio.wait_for(
                        socket.recv(), timeout=float(self.settings.intraday_subscription_refresh_seconds)
                    )
                except TimeoutError:
                    if subscribed and asyncio.get_running_loop().time() - last_packet_at > self.settings.intraday_feed_stale_seconds:
                        raise RuntimeError("Dhan live feed is stale.")
                    continue
                if not isinstance(packet, bytes):
                    continue
                last_packet_at = asyncio.get_running_loop().time()
                reason = DhanTickerPacketCodec.disconnect_reason(packet)
                if reason is not None:
                    raise RuntimeError(f"Dhan live feed disconnected with data error code {reason}.")
                yield packet


class MatsyaIntradayPaperWorker:
    def __init__(
        self,
        settings: MatsyaSettings,
        *,
        engine: IntradayPaperEngine | None = None,
        feed_client: FeedClient | None = None,
        dhan_client: DhanClient | None = None,
        token_service: MatsyaDhanTokenService | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine or IntradayPaperEngine()
        self.feed_client = feed_client or DhanV2WebSocketFeedClient(settings)
        self.dhan_client = dhan_client or DhanClient(settings.dhan_api_base_url)
        self.token_service = token_service or MatsyaDhanTokenService(settings)
        self.targets_by_symbol: dict[str, SubscriptionTarget] = {}
        self.reconnects = 0

    async def run(self) -> None:
        self.engine.sync_all_ledgers()
        await asyncio.gather(self._feed_loop(), self._reconciliation_loop())

    async def consume_packets(self, packets: AsyncIterator[bytes]) -> list[dict[str, Any]]:
        """Deterministic feed seam used by tests; it never exposes broker-order capability."""
        results: list[dict[str, Any]] = []
        async for packet in packets:
            tick = DhanTickerPacketCodec.parse(packet)
            if tick is None:
                continue
            symbol = self._symbol_for_security_id(tick.security_id)
            if not symbol:
                continue
            for strategy_id in self.engine.policies:
                if symbol in self.engine.desired_symbols_for(strategy_id):
                    results.append(self.engine.process_tick(strategy_id, symbol, tick))
        return results

    async def _feed_loop(self) -> None:
        backoff = 1
        while True:
            if not self.settings.intraday_paper_enabled:
                self.engine.update_feed_health(status="disabled", subscribed_symbols=[], detail="MATSYA_INTRADAY_PAPER_ENABLED=false")
                await asyncio.sleep(60)
                continue
            try:
                credentials = self.token_service.live_market_credentials()
                targets = self._refresh_targets()
                if not targets:
                    self.engine.update_feed_health(status="idle", subscribed_symbols=[], reconnects=self.reconnects)
                    await asyncio.sleep(self.settings.intraday_subscription_refresh_seconds)
                    continue
                self.engine.update_feed_health(
                    status="connecting", subscribed_symbols=[target.symbol for target in targets], reconnects=self.reconnects
                )
                async for packet in self.feed_client.stream(credentials, self._refresh_targets):
                    tick = DhanTickerPacketCodec.parse(packet)
                    if tick is None:
                        continue
                    symbol = self._symbol_for_security_id(tick.security_id)
                    if not symbol:
                        continue
                    for strategy_id in self.engine.policies:
                        if symbol in self.engine.desired_symbols_for(strategy_id):
                            self.engine.process_tick(strategy_id, symbol, tick)
                    current = self.engine.desired_symbols()
                    self.engine.update_feed_health(
                        status="live", subscribed_symbols=current, reconnects=self.reconnects
                    )
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.reconnects += 1
                self.engine.update_feed_health(
                    status="reconnecting",
                    subscribed_symbols=self.engine.desired_symbols(),
                    detail=_safe_error(exc),
                    reconnects=self.reconnects,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.settings.intraday_reconnect_max_seconds)

    async def _reconciliation_loop(self) -> None:
        completed_date: date | None = None
        while True:
            await asyncio.sleep(30)
            if not self.settings.intraday_paper_enabled:
                continue
            now_ist = datetime.now(tz=IST)
            cutoff = time(
                self.settings.intraday_reconciliation_hour_ist,
                self.settings.intraday_reconciliation_minute_ist,
            )
            if now_ist.weekday() >= 5 or now_ist.time().replace(tzinfo=None) < cutoff or completed_date == now_ist.date():
                continue
            try:
                await self.reconcile_session(now_ist.date())
                completed_date = now_ist.date()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.engine.update_feed_health(
                    status="recovery_failed",
                    subscribed_symbols=self.engine.desired_symbols(),
                    detail=_safe_error(exc),
                    reconnects=self.reconnects,
                )

    async def reconcile_session(self, session_date: date) -> dict[str, list[dict[str, Any]]]:
        credentials = self.token_service.live_market_credentials()
        targets = self._refresh_targets()
        candles_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for target in targets:
            payload = await self.dhan_client.historical_intraday(
                access_token=credentials.access_token,
                security_id=target.security_id,
                exchange_segment=target.exchange_segment,
                instrument="EQUITY",
                interval="1",
                from_date=f"{session_date.isoformat()} 09:15:00",
                to_date=f"{session_date.isoformat()} 15:31:00",
            )
            candles = parse_intraday_payload(payload)
            if candles:
                candles_by_symbol[target.symbol] = candles
        if targets and not candles_by_symbol:
            raise RuntimeError("Dhan intraday reconciliation returned no candles; pending entries were preserved.")
        return {
            strategy_id: self.engine.reconcile(strategy_id, session_date, candles_by_symbol)
            for strategy_id in self.engine.policies
        }

    def _refresh_targets(self) -> list[SubscriptionTarget]:
        symbols = self.engine.desired_symbols()
        if not symbols:
            self.targets_by_symbol = {}
            return []
        self.targets_by_symbol = resolve_subscription_targets(self.settings, symbols)
        missing = sorted(symbols - set(self.targets_by_symbol))
        if missing:
            raise RuntimeError(f"No Dhan security mapping for paper symbols: {','.join(missing)}")
        return list(self.targets_by_symbol.values())

    def _symbol_for_security_id(self, security_id: str) -> str | None:
        for symbol, target in self.targets_by_symbol.items():
            if target.security_id == security_id:
                return symbol
        return None


def resolve_subscription_targets(settings: MatsyaSettings, symbols: set[str]) -> dict[str, SubscriptionTarget]:
    if not symbols:
        return {}
    with connect(settings) as conn:
        run_schema(conn)
        rows = conn.execute(
            f"""
            SELECT m.symbol, mi.security_id
            FROM matsya.market_universe_members m
            {INSTRUMENT_LATERAL_JOIN_SQL}
            WHERE m.universe_name = %s AND m.active = true
              AND m.symbol = ANY(%s) AND mi.id IS NOT NULL
            """,
            (settings.ohlcv_universe_name, sorted(symbols)),
        ).fetchall()
    return {
        str(symbol): SubscriptionTarget(str(symbol), str(security_id), settings.dhan_historical_exchange_segment)
        for symbol, security_id in rows
    }


def parse_intraday_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("timestamp", "open", "high", "low", "close")
    arrays = {key: list(payload.get(key) or []) for key in keys}
    count = min((len(values) for values in arrays.values()), default=0)
    candles = []
    for index in range(count):
        epoch = int(arrays["timestamp"][index])
        row = {
            "timestamp": epoch,
            "open": float(arrays["open"][index]),
            "high": float(arrays["high"][index]),
            "low": float(arrays["low"][index]),
            "close": float(arrays["close"][index]),
        }
        if epoch > 0 and all(math_is_finite_positive(row[key]) for key in ("open", "high", "low", "close")):
            candles.append(row)
    return sorted(candles, key=lambda row: row["timestamp"])


def math_is_finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number > 0 and number not in {float("inf"), float("-inf")}


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for key in ("token=", "access-token", "clientId="):
        if key in text:
            return exc.__class__.__name__
    return text[:300]


def main() -> int:
    settings = MatsyaSettings.from_env()
    worker = MatsyaIntradayPaperWorker(settings)
    asyncio.run(worker.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
