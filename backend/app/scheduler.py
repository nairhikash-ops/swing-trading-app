import asyncio
import contextlib
import logging

from app.config import Settings
from app.token_service import TokenService


logger = logging.getLogger(__name__)


class RenewalScheduler:
    def __init__(self, settings: Settings, token_service: TokenService) -> None:
        self.settings = settings
        self.token_service = token_service
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="dhan-token-renewal")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                renewed, _, message = await self.token_service.renew_if_needed(force=False)
                if renewed:
                    logger.info("Dhan token auto-renewed.")
                elif message != "No Dhan token has been stored.":
                    logger.info("Dhan token renewal check: %s", message)
            except Exception:
                logger.exception("Unexpected Dhan token renewal scheduler error.")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.dhan_renew_check_interval_seconds)
            except TimeoutError:
                continue
