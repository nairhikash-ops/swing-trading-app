import asyncio
import logging
from app.matsya.renewal_worker import MatsyaRenewalWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if __name__ == "__main__":
    worker = MatsyaRenewalWorker()
    asyncio.run(worker.run())
