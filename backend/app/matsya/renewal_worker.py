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

        logger.info("Matsya renewal worker started. Interval: %ss", self.check_interval_seconds)

        while not self._shutdown:
            try:
                await self._check_and_renew()
            except Exception:
                logger.exception("Unexpected error in renewal worker loop.")
            
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
        
        logger.info("Token status: %s, expiry: %s", token_state, expiry)

        if token_state == "expiring_soon":
            logger.info("Token is expiring_soon. Attempting auto-renewal...")
            success, new_status, message = await self.service.renew()
            
            if success:
                logger.info("Renewal successful: %s. New expiry: %s", message, new_status.get("expiry_time"))
            else:
                logger.error("Renewal failed: %s", message)
        elif token_state == "expired":
            logger.warning("Token expired; manual update required.")
        elif token_state == "renew_failed":
            logger.warning("Previous renewal failed; manual intervention required.")
        elif token_state == "config_error":
            logger.error("Token config_error; auto-renewal aborted.")
        elif token_state == "unknown":
            logger.warning("Token state unknown; manual verification required.")
        elif token_state == "active":
            logger.debug("Token state is active, no renewal needed.")
        else:
            logger.debug("Unhandled token state: %s", token_state)
