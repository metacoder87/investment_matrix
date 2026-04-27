import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from app.config import settings
from app.models.instrument import Price, Coin
from database import session_scope
from celery_app import celery_app
from app.services.asset_status import classify_asset

logger = logging.getLogger("cryptoinsight.services.backfill")


class StartupGapFiller:
    @staticmethod
    def _normalize_symbol_for_exchange(symbol: str, exchange: str) -> str:
        symbol = symbol.strip().upper()
        exchange = exchange.strip().lower()
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            symbol = f"{base}-{quote}"
        if "-" in symbol:
            if exchange == "binance" and symbol.endswith("-USD"):
                return f"{symbol[:-4]}-USDT"
            return symbol
        if exchange in {"coinbase", "kraken"}:
            return f"{symbol}-USD"
        if exchange == "binance":
            return f"{symbol}-USDT"
        return symbol

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
        
        # 1. Update Coin List (Blocking call to ensure we have metadata)
        # We trigger the task and wait for it, or check if table is empty.
        with session_scope() as db:
            coin_count = db.query(func.count(Coin.id)).scalar()
        
        symbols: list[str] = []
        top_n = min(settings.TRACK_TOP_N_COINS or 50, 50)
        if coin_count == 0:
            logger.info("Coin list empty. Triggering ingestion and continuing with CORE_UNIVERSE.")
            celery_app.send_task("celery_worker.tasks.fetch_and_store_coin_list")
            symbols = cls.get_core_symbols()
        else:
            # 2. Select Dynamic Universe (Top N by Market Cap)
            top_n = min(settings.TRACK_TOP_N_COINS or 50, 50)
            with session_scope() as db:
                top_coins = (
                    db.query(Coin.symbol, Coin.id)
                    .filter(Coin.market_cap_rank <= top_n)
                    .order_by(Coin.market_cap_rank.asc())
                    .all()
                )

            symbols = [c.symbol.upper() for c in top_coins]

            # Fallback to config if DB query fails or returns empty (e.g. ranks not populated)
            if not symbols:
                symbols = cls.get_core_symbols()
        
        symbols = [symbol for symbol in symbols if classify_asset(symbol).is_analyzable]
        logger.info(f"Identified {len(symbols)} analyzable assets in active universe (Top {top_n}).")

        # 3. Queue Backfills
        exchange = "auto"
        
        backfill_count = 0
        with session_scope() as db:
            for symbol in symbols:
                # Normalize symbol for DB lookup (e.g. BTC-USD).
                # CoinGecko usually returns "btc", "eth". We map to exchange pairs here.
                symbol_pair = cls._normalize_symbol_for_exchange(symbol, exchange)

                last_ts = db.query(func.max(Price.timestamp)).filter(
                    Price.exchange == exchange,
                    Price.symbol == symbol_pair
                ).scalar()

                now = datetime.now(timezone.utc)
                
                if not last_ts:
                    # Case 1: No data. Full backfill.
                    backfill_count += 1
                    celery_app.send_task(
                        "celery_worker.tasks.backfill_historical_candles",
                        kwargs={
                            "symbol": symbol_pair,
                            "exchange_id": exchange,
                            "days": 7, # Default window
                            "timeframe": "1m"
                        }
                    )
                else:
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                    
                    gap = now - last_ts
                    if gap > timedelta(minutes=15): # Relaxed gap check
                        backfill_count += 1
                        celery_app.send_task(
                            "celery_worker.tasks.backfill_historical_candles",
                            kwargs={
                                "symbol": symbol_pair,
                                "exchange_id": exchange,
                                "start_from": last_ts.isoformat(),
                                "timeframe": "1m"
                            }
                        )
        
        logger.info(f"Queued backfill/gap-fill for {backfill_count} assets.")


async def bootstrap_universe() -> dict:
    """
    Bootstrap the database with top 500 coins on first startup.
    This runs once and stores a flag in the database to prevent re-running.
    
    Returns:
        dict: Status of bootstrap operation
    """
    logger.info("🚀 Starting Universe Bootstrap...")
    
    try:
        # Check if bootstrap already completed
        with session_scope() as db:
            coin_count = db.query(func.count(Coin.id)).scalar()
            
            # If we already have coins, skip bootstrap
            if coin_count > 100:
                logger.info(f"✅ Bootstrap skipped - {coin_count} coins already exist")
                return {"status": "skipped", "reason": "already_bootstrapped", "coin_count": coin_count}
        
        # Trigger coin list ingestion
        logger.info("📊 Fetching top 500 coins from CoinGecko...")
        try:
            task = celery_app.send_task("celery_worker.tasks.fetch_and_store_coin_list")
            logger.info(f"Coin list ingestion task queued: {task.id}")
        except Exception as e:
            logger.error(f"Failed to queue coin list ingestion: {e}")
            return {"status": "error", "message": str(e)}
        
        # Wait a bit for coins to be inserted
        await asyncio.sleep(5)
        
        # Get top N coins to backfill
        top_n = min(settings.TRACK_TOP_N_COINS or 50, 50)
        exchange = "auto"
        
        with session_scope() as db:
            # Get top coins by market cap rank
            top_coins = (
                db.query(Coin.symbol)
                .filter(Coin.market_cap_rank.isnot(None))
                .filter(Coin.market_cap_rank <= top_n)
                .order_by(Coin.market_cap_rank.asc())
                .limit(top_n)
                .all()
            )
            
            if not top_coins:
                logger.warning("⚠️ No coins found in database after ingestion. Using fallback list.")
                # Fallback to core universe
                symbols = StartupGapFiller.get_core_symbols()
            else:
                symbols = [c.symbol.upper() for c in top_coins]
        symbols = [symbol for symbol in symbols if classify_asset(symbol).is_analyzable]
        
        logger.info(f"📈 Queueing backfill for {len(symbols)} top coins...")
        
        # Queue backfill tasks (stagger to avoid rate limits)
        backfill_tasks = []
        for i, symbol in enumerate(symbols[:50]):
            symbol_pair = StartupGapFiller._normalize_symbol_for_exchange(symbol, exchange)
            
            try:
                task = celery_app.send_task(
                    "celery_worker.tasks.backfill_historical_candles",
                    kwargs={
                        "symbol": symbol_pair,
                        "exchange_id": exchange,
                        "days": 7,  # Start with 7 days of data
                        "timeframe": "1m"
                    },
                    countdown=(i * 2)  # Stagger by 2 seconds each
                )
                backfill_tasks.append(task.id)
                
                if (i + 1) % 10 == 0:
                    logger.info(f"  ⏳ Queued {i + 1}/{len(symbols[:50])} backfill tasks...")
                    
            except Exception as e:
                logger.error(f"Failed to queue backfill for {symbol_pair}: {e}")
        
        logger.info(f"✅ Bootstrap complete! Queued {len(backfill_tasks)} backfill tasks.")
        logger.info("⏳ Data ingestion will continue in background. Check /api/health for status.")
        
        return {
            "status": "success",
            "coins_identified": len(symbols),
            "backfills_queued": len(backfill_tasks),
            "task_ids": backfill_tasks[:10]  # Return first 10 task IDs
        }
        
    except Exception as e:
        logger.error(f"❌ Bootstrap failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

