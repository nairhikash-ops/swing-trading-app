import asyncio
import logging

from app.matsya.ohlcv_worker import MatsyaOHLCVWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if __name__ == "__main__":
    worker = MatsyaOHLCVWorker()
    asyncio.run(worker.run())
