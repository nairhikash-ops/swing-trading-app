import asyncio
import logging
import os
import signal
from typing import Any

from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import MatsyaDhanTokenService

logger = logging.getLogger(__name__)

class MatsyaRenewalWorker:
    def __init__(self) -> None:
        self.settings = MatsyaSettings.from_env()
        self.enabled = os.getenv("MATSYA_RENEWAL_WORKER_ENABLED", "false").lower() == "true"
        self.check_interval_seconds = int(os.getenv("MATSYA_RENEWAL_CHECK_INTERVAL_SECONDS", "900"))
        self.service = MatsyaDhanTokenService(self.settings)
        self._shutdown = False

    def handle_shutdown(self, *args: Any) -> None:
        logger.info("Matsya renewal worker shutting down...")
        self._shutdown = True

    async def run(self) -> None:
        if not self.enabled:
            logger.info("Matsya renewal worker is disabled. Exiting.")
            return

        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, self.handle_shutdown)
            loop.add_signal_handler(signal.SIGTERM, self.handle_shutdown)
        except NotImplementedError:
            # add_signal_handler is not implemented on Windows for asyncio
            signal.signal(signal.SIGINT, self.handle_shutdown)
            signal.signal(signal.SIGTERM, self.handle_shutdown)

        logger.info(f"Matsya renewal worker started. Interval: {self.check_interval_seconds}s")

        while not self._shutdown:
            try:
                await self._check_and_renew()
            except Exception as e:
                logger.error(f"Unexpected error in renewal worker: {e}", exc_info=True)
            
            # Sleep in small increments to allow responsive shutdown
            for _ in range(self.check_interval_seconds):
                if self._shutdown:
                    break
                await asyncio.sleep(1)

        logger.info("Matsya renewal worker stopped.")

    async def _check_and_renew(self) -> None:
        status = self.service.status()
        if not status.get("has_token"):
            logger.info("No Matsya token stored. Waiting...")
            return

        token_state = status.get("token_state")
        expiry = status.get("expiry_time")
        
        logger.info(f"Token status: {token_state}, expiry: {expiry}")

        if token_state in ["expiring_soon", "expired", "renew_failed"]:
            logger.info(f"Token is {token_state}. Attempting renewal...")
            success, new_status, message = await self.service.renew()
            
            if success:
                new_expiry = new_status.get("expiry_time")
                logger.info(f"Renewal successful: {message}. New expiry: {new_expiry}")
            else:
                logger.error(f"Renewal failed: {message}. Error: {new_status.get('last_error')}")
        else:
            logger.debug(f"Token state is {token_state}, no renewal needed.")
