from __future__ import annotations

import asyncio
import logging
import signal
from datetime import date, datetime, timedelta
from typing import Any

from app.matsya.ohlcv_service import MatsyaOHLCVService
from app.matsya.settings import MatsyaSettings
from app.timezone import IST


logger = logging.getLogger(__name__)


class MatsyaOHLCVWorker:
    def __init__(self, settings: MatsyaSettings | None = None, service: MatsyaOHLCVService | None = None) -> None:
        self.settings = settings or MatsyaSettings.from_env()
        self.service = service or MatsyaOHLCVService(self.settings)
        self._stop = asyncio.Event()

    def handle_shutdown(self, *args: Any) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not self.settings.ohlcv_worker_enabled:
            logger.info("Matsya OHLCV worker is disabled.")
            return

        loop = asyncio.get_running_loop()
        for signame in ("SIGINT", "SIGTERM"):
            signum = getattr(signal, signame, None)
            if signum is not None:
                try:
                    loop.add_signal_handler(signum, self.handle_shutdown)
                except NotImplementedError:
                    pass

        if not self.settings.ohlcv_loop:
            await self.run_once()
            return

        logger.info(
            "Matsya OHLCV worker loop started. Daily EOD hour IST: %s",
            self.settings.historical_finalized_after_hour_ist,
        )
        last_attempt_date: date | None = None
        while not self._stop.is_set():
            now_ist = datetime.now(tz=IST)
            if should_run_daily_eod(now_ist, self.settings.historical_finalized_after_hour_ist, last_attempt_date):
                await self.run_once()
                last_attempt_date = now_ist.date()
            else:
                logger.info(
                    "Matsya OHLCV worker waiting for daily EOD window. now_ist=%s next_run_ist=%s",
                    now_ist.isoformat(),
                    next_daily_eod_run_at(
                        now_ist,
                        self.settings.historical_finalized_after_hour_ist,
                        last_attempt_date,
                    ).isoformat(),
                )
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=seconds_until_next_check(
                        now_ist,
                        self.settings.historical_finalized_after_hour_ist,
                        self.settings.ohlcv_check_interval_seconds,
                        last_attempt_date,
                    ),
                )
            except TimeoutError:
                continue
        logger.info("Matsya OHLCV worker loop stopped.")

    async def run_once(self) -> dict[str, Any]:
        status = await self.service.run_once()
        logger.info(
            "Matsya OHLCV run status=%s queued=%s done=%s failed=%s skipped=%s",
            status.get("status"),
            status.get("queued_count"),
            status.get("done_count"),
            status.get("failed_count"),
            status.get("skipped_count"),
        )
        validation = self.service.validation_report()
        logger.info(
            "Matsya OHLCV validation total_rows=%s symbols=%s duplicates=%s null_ohlcv=%s "
            "bad_ohlc=%s negative_volume=%s zero_candle_symbols=%s stale_symbols=%s "
            "missing_recent_symbol_dates=%s expected_latest=%s validation_start=%s",
            validation.get("total_rows"),
            validation.get("symbols_with_candles"),
            validation.get("duplicate_count"),
            validation.get("null_ohlcv_count"),
            validation.get("bad_ohlc_count"),
            validation.get("negative_volume_count"),
            validation.get("zero_candle_symbols"),
            validation.get("stale_symbols"),
            validation.get("missing_recent_symbol_dates"),
            validation.get("expected_latest_candle_date"),
            validation.get("validation_start_date"),
        )
        return status


def should_run_daily_eod(now_ist: datetime, finalized_after_hour_ist: int, last_attempt_date: date | None) -> bool:
    resolved_now = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    if resolved_now.hour < finalized_after_hour_ist:
        return False
    return last_attempt_date != resolved_now.date()


def next_daily_eod_run_at(now_ist: datetime, finalized_after_hour_ist: int, last_attempt_date: date | None) -> datetime:
    resolved_now = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    today_eod = resolved_now.replace(
        hour=finalized_after_hour_ist,
        minute=0,
        second=0,
        microsecond=0,
    )
    if should_run_daily_eod(resolved_now, finalized_after_hour_ist, last_attempt_date):
        return resolved_now
    if resolved_now < today_eod:
        return today_eod
    return today_eod + timedelta(days=1)


def seconds_until_next_check(
    now_ist: datetime,
    finalized_after_hour_ist: int,
    check_interval_seconds: int,
    last_attempt_date: date | None,
) -> float:
    next_run = next_daily_eod_run_at(now_ist, finalized_after_hour_ist, last_attempt_date)
    wait_seconds = max(1.0, (next_run - now_ist.astimezone(IST)).total_seconds())
    return min(wait_seconds, max(60, check_interval_seconds))
