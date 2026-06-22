from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from app.matsya.ohlcv_service import MatsyaOHLCVService
from app.matsya.settings import MatsyaSettings


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

        logger.info("Matsya OHLCV worker loop started.")
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.ohlcv_check_interval_seconds,
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
        return status
