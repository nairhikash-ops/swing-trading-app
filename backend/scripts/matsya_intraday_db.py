from __future__ import annotations

import argparse
import asyncio
import csv
import os
from datetime import date, timedelta
from pathlib import Path

from app.matsya_intraday.database import (
    connect_intraday,
    derive_day,
    load_authoritative_daily,
    load_stored_day,
    migrate,
    store_day,
    store_reconciliation,
)
from app.matsya_intraday.reconciliation import reconcile
from app.matsya_intraday.service import fetch_and_validate
from app.matsya_intraday.settings import IntradaySettings
from app.matsya_intraday.validation import DayValidation


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manual validated Matsya one-minute ingestion")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply additive migrations to the separate intraday database")
    for name in ("ingest", "validate", "reconcile", "aggregate"):
        command = sub.add_parser(name)
        command.add_argument("--symbol", required=True)
        command.add_argument("--security-id", required=True)
        command.add_argument("--from-date", required=True)
        command.add_argument("--to-date", required=True)
        command.add_argument("--trading-dates", required=True, help="comma-separated completed NSE sessions")
        command.add_argument("--dry-run", action="store_true")
    pilot = sub.add_parser("pilot", help="run the same workflow for a symbol/security-id CSV")
    pilot.add_argument("--universe-csv", required=True, help="CSV with symbol and security_id columns")
    pilot.add_argument("--from-date", required=True)
    pilot.add_argument("--to-date", required=True)
    pilot.add_argument("--trading-dates", required=True)
    pilot.add_argument("--dry-run", action="store_true")
    return result


async def run(args: argparse.Namespace) -> None:
    settings = IntradaySettings.from_env()
    if args.command == "migrate":
        with connect_intraday(settings) as conn:
            print("migrations_applied=" + ",".join(migrate(conn)))
        return
    if args.command == "pilot":
        path = Path(args.universe_csv)
        with path.open(newline="", encoding="utf-8-sig") as handle:
            universe = list(csv.DictReader(handle))
        if not universe or any(not row.get("symbol") or not row.get("security_id") for row in universe):
            raise RuntimeError("pilot CSV must contain non-empty symbol and security_id columns")
        for index, row in enumerate(universe):
            await run(
                argparse.Namespace(
                    command="validate" if args.dry_run else "ingest",
                    symbol=row["symbol"], security_id=row["security_id"],
                    from_date=args.from_date, to_date=args.to_date,
                    trading_dates=args.trading_dates, dry_run=args.dry_run,
                )
            )
            if index + 1 < len(universe):
                await asyncio.sleep(0.55)
        return
    expected = [date.fromisoformat(value) for value in args.trading_dates.split(",")]
    if settings.trusted_start_date and min(expected) < settings.trusted_start_date:
        raise RuntimeError(f"requested date precedes trusted start {settings.trusted_start_date}")
    if args.command in {"reconcile", "aggregate"}:
        with connect_intraday(settings) as conn:
            if not args.dry_run:
                migrate(conn)
            for trading_day in expected:
                day_id, validation = load_stored_day(conn,args.symbol.upper(),args.security_id,trading_day.isoformat())
                if validation.status != "accepted":
                    raise RuntimeError(f"{args.symbol.upper()} {trading_day} is {validation.status}; only complete accepted days may be reconciled or aggregated")
                if args.command == "aggregate":
                    count = 0 if args.dry_run else derive_day(conn,day_id=day_id,symbol=args.symbol.upper(),security_id=args.security_id,validation=validation)
                    print(f"symbol={args.symbol.upper()} date={trading_day} derived={count} dry_run={args.dry_run}")
                else:
                    authoritative = load_authoritative_daily(settings,args.security_id,trading_day.isoformat())
                    result = reconcile(validation.candles,authoritative)
                    if not args.dry_run:
                        store_reconciliation(conn,day_id=day_id,symbol=args.symbol.upper(),security_id=args.security_id,
                                             trading_date=trading_day.isoformat(),result=result)
                    print(f"symbol={args.symbol.upper()} date={trading_day} structural_acceptance_gate_passed={result.structural_acceptance_gate_passed} "
                          f"open_high_low_match={result.open_high_low_match} close_match={result.close_match} "
                          f"volume_match={result.volume_match} cross_source_status={result.cross_source_status} "
                          f"explanation={result.explanation}")
        return
    token = os.getenv("MATSYA_MANUAL_DHAN_TOKEN", "")
    if not token:
        raise RuntimeError("MATSYA_MANUAL_DHAN_TOKEN is required and is never logged")
    request_from=args.from_date
    request_to=(date.fromisoformat(args.to_date)+timedelta(days=1)).isoformat()
    try:
        payload, validations, request_from, request_to = await fetch_and_validate(
            token=token, symbol=args.symbol.upper(), security_id=args.security_id,
            start=date.fromisoformat(args.from_date), end=date.fromisoformat(args.to_date), expected_dates=expected,
        )
    except Exception as exc:
        payload={"api_error_type":type(exc).__name__,"api_error":str(exc)[:500]}
        validations={day:DayValidation(day,"unavailable",(),(f"api_error:{type(exc).__name__}",),(),0) for day in expected}
    counts: dict[str, int] = {}
    for result in validations.values():
        counts[result.status] = counts.get(result.status, 0) + 1
    if args.dry_run or args.command == "validate":
        print(f"dry_run=true request={request_from}..{request_to} candles={sum(len(v.candles) for v in validations.values())} statuses={counts}")
        return
    if args.command != "ingest":
        raise RuntimeError(f"{args.command} requires stored symbol-days; use the dedicated database workflow described in the runbook")
    with connect_intraday(settings) as conn:
        migrate(conn)
        run_id = conn.execute(
            """INSERT INTO matsya_intraday.ingestion_runs(command,dry_run,requested_from,requested_to,universe,status,requests_made,candles_fetched)
               VALUES ('ingest',false,%s,%s,%s::jsonb,'running',1,%s) RETURNING id""",
            (args.from_date,args.to_date,'["'+args.symbol.upper()+'"]',sum(len(v.candles) for v in validations.values())),
        ).fetchone()[0]
        conn.commit()
        for result in validations.values():
            store_day(conn,run_id=run_id,symbol=args.symbol.upper(),security_id=args.security_id,validation=result,
                      request_from=request_from,request_to=request_to,payload=payload)
        conn.execute("UPDATE matsya_intraday.ingestion_runs SET status='completed',completed_at=now() WHERE id=%s",(run_id,))
        conn.commit()
    print(f"run_id={run_id} statuses={counts}")


def main() -> None:
    asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
