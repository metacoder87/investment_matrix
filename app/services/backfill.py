import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from app.config import settings
from app.models.instrument import Price
from database import session_scope
from celery_app import celery_app

logger = logging.getLogger("cryptoinsight.services.backfill")


class StartupGapFiller:
    @staticmethod
    def get_core_symbols() -> list[str]:
        """Returns list of symbols from config to check on startup."""
        raw = settings.CORE_UNIVERSE
        if not raw:
            return ["BTC-USD", "ETH-USD"]
        return [s.strip().upper() for s in raw.split(",") if s.strip()]

    @classmethod
    async def run_startup_check(cls):
        """
        Non-blocking check that runs on app startup.
        Identifies gaps in core universe data and queues backfills.
        """
        # Run in a separate thread/task to avoid blocking startup
        asyncio.create_task(cls._check_and_fill())

    @classmethod
    async def _check_and_fill(cls):
        logger.info("Starting Smart Gap-Fill check...")
        symbols = cls.get_core_symbols()
        
        # We assume Coinbase for backfilling core USD pairs for now, 
        # as it's the default safe "US-friendly" exchange in the stack.
        # Ideally, we map symbol -> primary exchange.
        exchange = settings.STREAM_EXCHANGE.lower() or "coinbase"

        with session_scope() as db:
            for symbol in symbols:
                # Find last timestamp
                # Note: symbol stored in DB is normalized (usually "BTC-USD")
                last_ts = db.query(func.max(Price.timestamp)).filter(
                    Price.symbol == symbol
                ).scalar()

                now = datetime.now(timezone.utc)
                
                if not last_ts:
                    # Case 1: No data at all. Backfill configured "Days" (default 7).
                    logger.info("No data found for %s. Triggering full backfill.", symbol)
                    celery_app.send_task(
                        "celery_worker.tasks.backfill_historical_candles",
                        kwargs={
                            "symbol": symbol,
                            "exchange_id": exchange,
                            "days": 7, # Default initial depth
                            "timeframe": "1m"
                        }
                    )
                else:
                    # Ensure timezone awareness
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                    
                    gap = now - last_ts
                    
                    # If gap > 5 minutes, fill it.
                    if gap > timedelta(minutes=5):
                        logger.info("Detected gap of %s for %s. Last data: %s", gap, symbol, last_ts)
                        
                        # Trigger backfill starting from last_ts
                        celery_app.send_task(
                            "celery_worker.tasks.backfill_historical_candles",
                            kwargs={
                                "symbol": symbol,
                                "exchange_id": exchange,
                                "start_from": last_ts.isoformat(),
                                "timeframe": "1m"
                            }
                        )
                    else:
                        logger.info("%s is up to date (gap: %s).", symbol, gap)

        logger.info("Smart Gap-Fill check queued.")
