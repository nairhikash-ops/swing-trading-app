from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.matsya.ohlcv_service import MatsyaOHLCVService
from app.matsya.settings import MatsyaSettings
from app.timezone import IST


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledStage:
    name: str
    run_at: time
    action: str


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

        stages = schedule_stages(self.settings)
        logger.info(
            "Matsya OHLCV worker loop started. primary=%s repair=%s final_check=%s deadline=%s IST",
            stages[0].run_at.strftime("%H:%M"),
            stages[1].run_at.strftime("%H:%M"),
            stages[2].run_at.strftime("%H:%M"),
            ready_deadline_time(self.settings).strftime("%H:%M"),
        )
        deadline = ready_deadline_time(self.settings)
        completed_stages = initial_completed_schedule_stages(
            datetime.now(tz=IST),
            self.service.latest_status(),
            stages,
        )
        while not self._stop.is_set():
            now_ist = datetime.now(tz=IST)
            if completed_stages and next(iter(completed_stages)).date != now_ist.date():
                completed_stages = set()
            stage = due_schedule_stage(now_ist, stages, completed_stages, deadline)
            if stage and stage.action == "fetch":
                logger.info("Matsya OHLCV scheduled %s fetch starting.", stage.name)
                await self.run_once()
                completed_stages.add(ScheduleKey(now_ist.date(), stage.name))
            elif stage and stage.action == "validate":
                self.log_readiness_check(stage.name)
                completed_stages.add(ScheduleKey(now_ist.date(), stage.name))
            else:
                next_run = next_scheduled_run_at(now_ist, stages, completed_stages, deadline)
                logger.info(
                    "Matsya OHLCV worker waiting for schedule. now_ist=%s next_run_ist=%s",
                    now_ist.isoformat(),
                    next_run.isoformat(),
                )
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=seconds_until_next_check(
                        now_ist,
                        self.settings.ohlcv_check_interval_seconds,
                        stages,
                        completed_stages,
                        deadline,
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

    def log_readiness_check(self, stage_name: str) -> dict[str, Any]:
        validation = self.service.validation_report()
        issues = {
            key: validation.get(key)
            for key in (
                "duplicate_count",
                "null_ohlcv_count",
                "bad_ohlc_count",
                "negative_volume_count",
                "zero_candle_symbols",
                "stale_symbols",
                "missing_recent_symbol_dates",
            )
        }
        has_issues = any(int(value or 0) > 0 for value in issues.values())
        logger_fn = logger.warning if has_issues else logger.info
        logger_fn(
            "Matsya OHLCV %s readiness total_rows=%s symbols=%s expected_latest=%s deadline=%s "
            "duplicates=%s null_ohlcv=%s bad_ohlc=%s negative_volume=%s zero_candle_symbols=%s "
            "stale_symbols=%s missing_recent_symbol_dates=%s",
            stage_name,
            validation.get("total_rows"),
            validation.get("symbols_with_candles"),
            validation.get("expected_latest_candle_date"),
            ready_deadline_time(self.settings).strftime("%H:%M"),
            validation.get("duplicate_count"),
            validation.get("null_ohlcv_count"),
            validation.get("bad_ohlc_count"),
            validation.get("negative_volume_count"),
            validation.get("zero_candle_symbols"),
            validation.get("stale_symbols"),
            validation.get("missing_recent_symbol_dates"),
        )
        return validation


@dataclass(frozen=True)
class ScheduleKey:
    date: date
    stage_name: str


def schedule_stages(settings: MatsyaSettings) -> list[ScheduledStage]:
    return [
        ScheduledStage(
            "primary",
            time(settings.ohlcv_primary_run_hour_ist, settings.ohlcv_primary_run_minute_ist, tzinfo=IST),
            "fetch",
        ),
        ScheduledStage(
            "repair",
            time(settings.ohlcv_repair_run_hour_ist, settings.ohlcv_repair_run_minute_ist, tzinfo=IST),
            "fetch",
        ),
        ScheduledStage(
            "final_check",
            time(settings.ohlcv_final_check_hour_ist, settings.ohlcv_final_check_minute_ist, tzinfo=IST),
            "validate",
        ),
    ]


def ready_deadline_time(settings: MatsyaSettings) -> time:
    return time(settings.ohlcv_ready_deadline_hour_ist, settings.ohlcv_ready_deadline_minute_ist, tzinfo=IST)


def initial_completed_schedule_stages(
    now_ist: datetime,
    latest_status: dict[str, Any] | None,
    stages: list[ScheduledStage],
) -> set[ScheduleKey]:
    if not latest_status or latest_status.get("status") not in {"completed", "completed_with_errors", "failed"}:
        return set()
    resolved_now = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    completed: set[ScheduleKey] = set()
    for key in ("completed_at", "updated_at", "started_at"):
        attempted_at = datetime_value_ist(latest_status.get(key))
        if attempted_at and attempted_at.date() == resolved_now.date():
            attempted_time = attempted_at.timetz()
            for stage in stages:
                if stage.action == "fetch" and stage.run_at <= attempted_time:
                    completed.add(ScheduleKey(resolved_now.date(), stage.name))
            if attempted_time >= stages[-1].run_at:
                for stage in stages:
                    completed.add(ScheduleKey(resolved_now.date(), stage.name))
            return completed
    return completed


def due_schedule_stage(
    now_ist: datetime,
    stages: list[ScheduledStage],
    completed_stages: set[ScheduleKey],
    deadline: time,
) -> ScheduledStage | None:
    resolved_now = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    if resolved_now.timetz() >= deadline:
        return None
    for stage in stages:
        if ScheduleKey(resolved_now.date(), stage.name) in completed_stages:
            continue
        if resolved_now.timetz() >= stage.run_at:
            return stage
    return None


def next_scheduled_run_at(
    now_ist: datetime,
    stages: list[ScheduledStage],
    completed_stages: set[ScheduleKey],
    deadline: time,
) -> datetime:
    resolved_now = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    if resolved_now.timetz() >= deadline:
        return datetime.combine(resolved_now.date() + timedelta(days=1), stages[0].run_at, tzinfo=IST)
    for stage in stages:
        stage_at = datetime.combine(resolved_now.date(), stage.run_at, tzinfo=IST)
        if ScheduleKey(resolved_now.date(), stage.name) not in completed_stages and stage_at > resolved_now:
            return stage_at
    return datetime.combine(resolved_now.date() + timedelta(days=1), stages[0].run_at, tzinfo=IST)


def seconds_until_next_check(
    now_ist: datetime,
    check_interval_seconds: int,
    stages: list[ScheduledStage],
    completed_stages: set[ScheduleKey],
    deadline: time,
) -> float:
    next_run = next_scheduled_run_at(now_ist, stages, completed_stages, deadline)
    wait_seconds = max(1.0, (next_run - now_ist.astimezone(IST)).total_seconds())
    return min(wait_seconds, max(60, check_interval_seconds))


def datetime_value_ist(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(IST) if value.tzinfo else value.replace(tzinfo=IST)
    parsed = datetime.fromisoformat(str(value))
    return parsed.astimezone(IST) if parsed.tzinfo else parsed.replace(tzinfo=IST)
