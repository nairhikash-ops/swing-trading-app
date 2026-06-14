import asyncio
import contextlib
import logging

from app.config import Settings
from app.historical_data import HistoricalDataService
from app.schemas import TokenStatusResponse
from app.timezone import now_utc
from app.token_service import TokenService


logger = logging.getLogger(__name__)


class DataMaintenanceScheduler:
    def __init__(
        self,
        settings: Settings,
        token_service: TokenService,
        historical_service: HistoricalDataService,
    ) -> None:
        self.settings = settings
        self.token_service = token_service
        self.historical_service = historical_service
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if not self.settings.data_maintenance_enabled:
            logger.info("Data maintenance scheduler disabled.")
            return
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="data-maintenance")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def run_once(self) -> dict[str, object]:
        renewed, status, token_message = await self.token_service.renew_if_needed(force=False)
        if not token_can_fetch(status):
            reason = status.historical_block_reason or token_message
            logger.info("Data maintenance skipped: %s", reason)
            return {
                "status": "skipped",
                "reason": reason,
                "token_state": status.state,
                "data_api_active": status.data_api_active,
                "historical_fetch_allowed": status.historical_fetch_allowed,
                "historical_block_reason": status.historical_block_reason,
                "renewed": renewed,
            }

        retention_result: dict[str, object] = {
            "retention_status": "disabled",
            "deleted_candle_count": 0,
        }
        if self.settings.auto_purge_market_data:
            retention_result = {
                "retention_status": "purged",
                **self.historical_service.prune_retention_window(),
            }
        historical_status = await self.historical_service.start_or_resume_nifty_500_fetch()
        result: dict[str, object] = {
            "status": "ok",
            "renewed": renewed,
            "historical_status": historical_status.get("status"),
            "historical_run_id": historical_status.get("id"),
            **retention_result,
        }

        logger.info(
            "Data maintenance result: status=%s run_id=%s",
            result.get("historical_status"),
            result.get("historical_run_id"),
        )
        return result

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Unexpected data maintenance scheduler error.")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.data_maintenance_check_interval_seconds,
                )
            except TimeoutError:
                continue


def token_can_fetch(status: TokenStatusResponse) -> bool:
    if not status.has_token or status.state in ("missing", "expired", "config_error"):
        return False
    if status.expiry_time is not None and status.expiry_time <= now_utc():
        return False
    return status.historical_fetch_allowed
