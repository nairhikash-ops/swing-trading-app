from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backtesting.data import MatsyaPostgresDataSource
from app.backtesting.execution import IntradayExecutionConfig, IntradayExecutionEngine
from app.backtesting.intraday import MatsyaIntradayDataSource, merge_required_windows, parse_dhan_intraday_payload
from app.backtesting.strategies.mtf_weekly_trap import (
    WeeklyTrapConfig,
    build_intraday_orders,
    prepare_daily_traps,
    required_intraday_windows,
)
from app.dhan_client import DhanClient
from app.matsya.db import connect, run_schema
from app.matsya.repository import upsert_ohlcv_intraday_many
from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import MatsyaDhanTokenService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Candidate-driven MTF weekly-trap backtest")
    result.add_argument("action", choices=["plan", "fetch", "run"])
    result.add_argument("--plan-dir", type=Path, required=True)
    result.add_argument("--output-dir", type=Path)
    result.add_argument("--start-date", default="2021-07-01")
    result.add_argument("--end-date")
    result.add_argument("--liquidity-top-n", type=int, default=150)
    result.add_argument("--max-holding-sessions", type=int, default=20)
    result.add_argument("--refresh-completed", action="store_true")
    result.add_argument("--slippage-bps", type=float, default=5.0)
    result.add_argument("--round-trip-cost-bps", type=float, default=15.0)
    return result


def config_from_args(args: argparse.Namespace) -> WeeklyTrapConfig:
    return WeeklyTrapConfig(
        liquidity_top_n=args.liquidity_top_n,
        max_holding_sessions=args.max_holding_sessions,
    )


def build_plan(args: argparse.Namespace, settings: MatsyaSettings) -> None:
    args.plan_dir.mkdir(parents=True, exist_ok=False)
    cfg = config_from_args(args)
    requested_start = pd.Timestamp(args.start_date)
    warmup_start = (requested_start - pd.Timedelta(days=180)).date().isoformat()
    data_end = (pd.Timestamp(args.end_date) + pd.Timedelta(days=45)).date().isoformat() if args.end_date else None
    daily = MatsyaPostgresDataSource(settings.database_url).load(start_date=warmup_start, end_date=data_end)
    candidates = prepare_daily_traps(daily, cfg)
    candidates = candidates[candidates["date"] >= requested_start]
    if args.end_date:
        candidates = candidates[candidates["date"] <= pd.Timestamp(args.end_date)]
    windows = merge_required_windows(required_intraday_windows(daily, candidates, cfg))
    candidates.assign(date=candidates["date"].dt.strftime("%Y-%m-%d")).to_csv(args.plan_dir / "candidates.csv", index=False)
    pd.DataFrame(
        [{"symbol": item.symbol, "from_date": item.start_date, "to_date": item.end_date} for item in windows]
    ).to_csv(args.plan_dir / "fetch_plan.csv", index=False)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "mtf_weekly_trap_v1",
        "parameters": cfg.to_dict(),
        "daily_rows": len(daily), "symbols": int(daily["symbol"].nunique()),
        "candidate_count": len(candidates), "fetch_window_count": len(windows),
        "date_range": [args.start_date, str(daily["date"].max().date()) if not args.end_date else args.end_date],
        "daily_load_range": [str(daily["date"].min().date()), str(daily["date"].max().date())],
        "known_biases": ["current NIFTY_500 membership creates survivorship bias", "liquidity rank uses only prior sessions"],
    }
    (args.plan_dir / "plan_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def _instrument_map(conn: Any, symbols: list[str]) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT upper(mu.symbol), i.security_id
        FROM matsya.market_universe_members mu
        JOIN LATERAL (
            SELECT candidate.security_id FROM matsya.instruments candidate
            WHERE candidate.provider_code='dhan' AND candidate.active=true
              AND candidate.exchange_id='NSE' AND candidate.segment='E' AND candidate.instrument='EQUITY'
              AND ((btrim(candidate.isin)<>'' AND btrim(mu.isin)<>'' AND upper(btrim(candidate.isin))=upper(btrim(mu.isin)))
                OR (upper(btrim(candidate.symbol_name))=upper(btrim(mu.symbol))))
            ORDER BY CASE WHEN candidate.series='EQ' THEN 0 ELSE 1 END, candidate.id LIMIT 1
        ) i ON true
        WHERE mu.universe_name='NIFTY_500' AND mu.active=true AND upper(mu.symbol)=ANY(%s)
        """,
        (symbols,),
    ).fetchall()
    return {str(symbol): str(security_id) for symbol, security_id in rows}


def _access_token(settings: MatsyaSettings) -> str:
    direct = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    if direct:
        return direct
    try:
        return MatsyaDhanTokenService(settings).live_market_credentials().access_token
    except ValueError as exc:
        raise RuntimeError(
            "No usable Dhan token is available. Store it through Matsya setup or provide DHAN_ACCESS_TOKEN only in the process environment."
        ) from exc


async def fetch_plan(args: argparse.Namespace, settings: MatsyaSettings) -> None:
    plan = pd.read_csv(args.plan_dir / "fetch_plan.csv")
    token = _access_token(settings)
    client = DhanClient(settings.dhan_api_base_url)
    counts = {"completed": 0, "cached": 0, "failed": 0, "candles": 0}
    with connect(settings) as conn:
        run_schema(conn)
        mapping = _instrument_map(conn, sorted(set(plan["symbol"].str.upper())))
        for row in plan.itertuples(index=False):
            symbol = str(row.symbol).upper()
            security_id = mapping.get(symbol)
            if not security_id:
                counts["failed"] += 1
                continue
            from_date, to_date = date.fromisoformat(str(row.from_date)), date.fromisoformat(str(row.to_date))
            status = conn.execute(
                """SELECT status FROM matsya.ohlcv_intraday_fetch_windows
                   WHERE provider_code='dhan' AND security_id=%s AND interval_minutes=15
                     AND from_date=%s AND to_date=%s""",
                (security_id, from_date, to_date),
            ).fetchone()
            if status and status[0] == "completed" and not args.refresh_completed:
                counts["cached"] += 1
                continue
            conn.execute(
                """INSERT INTO matsya.ohlcv_intraday_fetch_windows
                       (provider_code,security_id,interval_minutes,from_date,to_date,status,started_at,error_message)
                   VALUES ('dhan',%s,15,%s,%s,'running',now(),'')
                   ON CONFLICT (provider_code,security_id,interval_minutes,from_date,to_date) DO UPDATE
                   SET status='running',started_at=now(),error_message='',updated_at=now()""",
                (security_id, from_date, to_date),
            )
            conn.commit()
            try:
                payload = await client.historical_intraday(
                    token, security_id, "NSE_EQ", "EQUITY",
                    f"{from_date.isoformat()} 09:15:00", f"{(to_date + timedelta(days=1)).isoformat()} 00:00:00", "15",
                )
                frame = parse_dhan_intraday_payload(payload, symbol=symbol)
                archive_rows = [
                    {
                        "provider_code": "dhan", "security_id": security_id, "exchange_segment": "NSE_EQ",
                        "instrument": "EQUITY", "interval_minutes": 15, "candle_time": item.timestamp.to_pydatetime(),
                        "open_price": item.open, "high_price": item.high, "low_price": item.low,
                        "close_price": item.close, "volume": item.volume, "open_interest": None,
                        "raw_candle": {"symbol": symbol, "timestamp": int(item.timestamp.timestamp())},
                    }
                    for item in frame.itertuples(index=False)
                ]
                upsert_ohlcv_intraday_many(conn, archive_rows)
                conn.execute(
                    """UPDATE matsya.ohlcv_intraday_fetch_windows SET status='completed',candles_received=%s,
                       completed_at=now(),updated_at=now() WHERE provider_code='dhan' AND security_id=%s
                       AND interval_minutes=15 AND from_date=%s AND to_date=%s""",
                    (len(archive_rows), security_id, from_date, to_date),
                )
                conn.commit()
                counts["completed"] += 1
                counts["candles"] += len(archive_rows)
            except Exception as exc:
                conn.rollback()
                safe_error = f"{exc.__class__.__name__}: request failed"[:500]
                conn.execute(
                    """UPDATE matsya.ohlcv_intraday_fetch_windows SET status='failed',error_message=%s,updated_at=now()
                       WHERE provider_code='dhan' AND security_id=%s AND interval_minutes=15 AND from_date=%s AND to_date=%s""",
                    (safe_error, security_id, from_date, to_date),
                )
                conn.commit()
                counts["failed"] += 1
            await asyncio.sleep(0.21)
    print(json.dumps(counts, indent=2))


def run_backtest(args: argparse.Namespace, settings: MatsyaSettings) -> None:
    if args.output_dir is None:
        raise ValueError("--output-dir is required for run")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    cfg = config_from_args(args)
    candidates = pd.read_csv(args.plan_dir / "candidates.csv", parse_dates=["date"])
    manifest = json.loads((args.plan_dir / "plan_manifest.json").read_text(encoding="utf-8"))
    start_date, end_date = manifest["daily_load_range"]
    daily = MatsyaPostgresDataSource(settings.database_url).load(start_date=start_date, end_date=end_date)
    intraday = MatsyaIntradayDataSource(settings.database_url).load(
        start_date=manifest["date_range"][0], end_date=end_date, symbols=candidates["symbol"].unique()
    )
    if intraday.empty:
        raise RuntimeError("No archived 15-minute candles are available; run fetch after supplying a usable Dhan token.")
    orders, pre_rejections = build_intraday_orders(daily, intraday, candidates, cfg)
    trades = IntradayExecutionEngine(
        IntradayExecutionConfig(slippage_bps=args.slippage_bps, round_trip_cost_bps=args.round_trip_cost_bps)
    ).run(intraday, orders)
    filled = trades[trades["status"] == "filled"]
    candidate_dates = sorted(pd.to_datetime(candidates["date"]).dt.date.unique())
    split_date = candidate_dates[min(len(candidate_dates) - 1, int(len(candidate_dates) * 0.70))] if candidate_dates else None
    activation_dates = pd.to_datetime(filled["activation_time"], utc=True).dt.tz_convert("Asia/Kolkata").dt.date if len(filled) else pd.Series(dtype=object)

    def metrics(frame: pd.DataFrame) -> dict[str, Any]:
        values = pd.to_numeric(frame["net_r"], errors="coerce").dropna()
        gains, losses = values[values > 0], values[values < 0]
        curve = values.cumsum()
        drawdown = curve - curve.cummax() if len(curve) else curve
        return {
            "trades": len(values), "win_rate": float((values > 0).mean()) if len(values) else None,
            "average_net_r": float(values.mean()) if len(values) else None,
            "median_net_r": float(values.median()) if len(values) else None,
            "total_net_r": float(values.sum()) if len(values) else None,
            "profit_factor": float(gains.sum() / abs(losses.sum())) if len(losses) and abs(losses.sum()) else None,
            "max_drawdown_r": float(drawdown.min()) if len(drawdown) else None,
        }

    execution_rejections = trades.loc[trades["status"] != "filled", "exit_reason"].value_counts().to_dict()
    preparation_rejections = pre_rejections["reason"].value_counts().to_dict() if len(pre_rejections) else {}
    summary = {
        "strategy": "mtf_weekly_trap_v1", "candidate_count": len(candidates),
        "orders_built": len(orders), "pre_execution_rejections": len(pre_rejections),
        "split_date": None if split_date is None else split_date.isoformat(),
        "overall": metrics(filled),
        "in_sample": metrics(filled[activation_dates < split_date]) if split_date else metrics(filled.iloc[0:0]),
        "out_of_sample": metrics(filled[activation_dates >= split_date]) if split_date else metrics(filled.iloc[0:0]),
        "by_side": {side: metrics(group) for side, group in filled.groupby("side")},
        "rejection_reasons": {"preparation": preparation_rejections, "execution": execution_rejections},
        "costs": {"slippage_bps_each_fill": args.slippage_bps, "round_trip_cost_bps": args.round_trip_cost_bps},
        "biases": manifest["known_biases"],
    }
    trades["cumulative_net_r"] = pd.NA
    if len(filled):
        trades.loc[filled.index, "cumulative_net_r"] = filled["net_r"].cumsum()
    trades.to_csv(args.output_dir / "trades.csv", index=False)
    pre_rejections.to_csv(args.output_dir / "candidate_rejections.csv", index=False)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps({**manifest, "execution": summary["costs"], "created_at_utc": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


def main() -> None:
    args = parser().parse_args()
    settings = MatsyaSettings.from_env()
    if args.action == "plan":
        build_plan(args, settings)
    elif args.action == "fetch":
        asyncio.run(fetch_plan(args, settings))
    else:
        run_backtest(args, settings)


if __name__ == "__main__":
    main()
