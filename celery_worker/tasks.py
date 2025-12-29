from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import ccxt.async_support as ccxt

from app.connectors.fundamental import CoinGeckoConnector
from app.models.instrument import Coin, Price
from celery_app import celery_app
from database import session_scope

logger = logging.getLogger("cryptoinsight.tasks")


def _normalize_symbol(symbol: str, exchange_id: str) -> str:
    """Normalize symbol format for different exchanges."""
    symbol = symbol.strip().upper()
    # Convert dash format to slash for CCXT
    if "-" in symbol and "/" not in symbol:
        base, quote = symbol.split("-", 1)
        symbol = f"{base}/{quote}"
    # Binance uses USDT instead of USD
    if exchange_id == "binance" and symbol.endswith("/USD"):
        symbol = symbol[:-3] + "USDT"
    return symbol


@celery_app.task
def ingest_historical_data(
    symbol: str,
    timeframe: str = "1m",
    limit: int = 100,
    exchange_id: str = "coinbase",
):
    """
    Ingests historical price data for a given symbol (basic version).
    """
    symbol = _normalize_symbol(symbol, exchange_id)
    
    async def fetch():
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown exchange_id={exchange_id!r} (must be a CCXT exchange id)")
        exchange = exchange_cls({"enableRateLimit": True})
        try:
            timeframe_seconds = exchange.parse_timeframe(timeframe)
            since = exchange.milliseconds() - limit * timeframe_seconds * 1000
            return await exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=since,
                limit=limit,
            )
        finally:
            await exchange.close()

    ohlcv = asyncio.run(fetch())

    with session_scope() as db:
        for row in ohlcv:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            price = Price(
                symbol=symbol,
                timestamp=ts,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            db.add(price)
    return f"Successfully ingested {len(ohlcv)} data points for {symbol}"


@celery_app.task(bind=True)
def backfill_historical_candles(
    self,
    symbol: str,
    exchange_id: str = "coinbase",
    timeframe: str = "1m",
    days: int = 7,
    start_from: Optional[str] = None,
):
    """
    Backfill historical OHLCV candles for a symbol.
    
    Fetches data in chunks to handle rate limits and large date ranges.
    Uses upsert logic to avoid duplicates.
    
    Args:
        symbol: Trading pair (e.g., "BTC-USD" or "BTC/USDT")
        exchange_id: CCXT exchange ID (default: binance)
        timeframe: Candle timeframe (default: 1m)
        days: Number of days to backfill (default: 7)
        start_from: Optional ISO timestamp to start from (for resuming)
    """
    symbol_ccxt = _normalize_symbol(symbol, exchange_id)
    symbol_db = symbol.strip().upper().replace("/", "-")
    
    async def fetch_all():
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown exchange_id={exchange_id!r}")
        
        exchange = exchange_cls({"enableRateLimit": True})
        all_candles = []
        
        try:
            timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
            
            # Calculate time range
            end_time = exchange.milliseconds()
            if start_from:
                start_time = int(datetime.fromisoformat(start_from.replace("Z", "+00:00")).timestamp() * 1000)
            else:
                start_time = end_time - (days * 24 * 60 * 60 * 1000)
            
            # Fetch in chunks (most exchanges limit to 1000 candles per request)
            chunk_size = 1000
            current_since = start_time
            total_fetched = 0
            
            while current_since < end_time:
                try:
                    candles = await exchange.fetch_ohlcv(
                        symbol_ccxt,
                        timeframe=timeframe,
                        since=current_since,
                        limit=chunk_size,
                    )
                    
                    if not candles:
                        break
                    
                    all_candles.extend(candles)
                    total_fetched += len(candles)
                    
                    # Move to next chunk
                    last_ts = candles[-1][0]
                    current_since = last_ts + timeframe_ms
                    
                    # Update task progress
                    progress = min(100, int((current_since - start_time) / (end_time - start_time) * 100))
                    self.update_state(state="PROGRESS", meta={"progress": progress, "fetched": total_fetched})
                    
                    # Rate limit protection
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    logger.warning(f"Chunk fetch error at {current_since}: {e}")
                    await asyncio.sleep(1)
                    continue
            
            return all_candles
            
        finally:
            await exchange.close()
    
    logger.info(f"Starting backfill for {symbol_ccxt} ({days} days, {timeframe})")
    candles = asyncio.run(fetch_all())
    
    if not candles:
        return {"status": "no_data", "symbol": symbol_db, "fetched": 0}
    
    # Store in database with upsert logic
    inserted = 0
    skipped = 0
    
    with session_scope() as db:
        for row in candles:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            
            # Check for existing record
            existing = db.query(Price).filter(
                Price.symbol == symbol_db,
                Price.timestamp == ts
            ).first()
            
            if existing:
                skipped += 1
                continue
            
            price = Price(
                symbol=symbol_db,
                timestamp=ts,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            db.add(price)
            inserted += 1
    
    result = {
        "status": "success",
        "symbol": symbol_db,
        "exchange": exchange_id,
        "timeframe": timeframe,
        "days": days,
        "total_fetched": len(candles),
        "inserted": inserted,
        "skipped": skipped,
    }
    logger.info(f"Backfill complete: {result}")
    return result


@celery_app.task
def backfill_core_universe(
    exchange_id: str = "coinbase",
    symbols: Optional[list] = None,
    days: int = 7,
):
    """
    Backfill historical data for the core universe of trading pairs.
    
    This is typically called on startup to ensure charts have historical data.
    Uses Coinbase Pro by default as it's accessible in the US (unlike Binance.com).
    """
    if symbols is None:
        # Default core universe - use USD pairs for Coinbase
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD"]
    
    results = []
    for symbol in symbols:
        try:
            result = backfill_historical_candles.delay(
                symbol=symbol,
                exchange_id=exchange_id,
                days=days,
            )
            results.append({"symbol": symbol, "task_id": result.id})
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})
    
    return {"status": "queued", "tasks": results}


@celery_app.task
def detect_and_fill_gaps(
    symbol: str,
    exchange_id: str = "coinbase",
    timeframe: str = "1m",
    max_gap_minutes: int = 60,
):
    """
    Detect gaps in stored price data and backfill them.
    """
    symbol_db = symbol.strip().upper().replace("/", "-")
    timeframe_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(timeframe, 1)
    
    gaps_found = []
    
    with session_scope() as db:
        # Get all timestamps for this symbol, ordered
        prices = db.query(Price.timestamp).filter(
            Price.symbol == symbol_db
        ).order_by(Price.timestamp.asc()).all()
        
        if len(prices) < 2:
            return {"status": "insufficient_data", "symbol": symbol_db}
        
        # Find gaps
        prev_ts = prices[0][0]
        for (current_ts,) in prices[1:]:
            expected_next = prev_ts + timedelta(minutes=timeframe_minutes)
            gap_minutes = (current_ts - expected_next).total_seconds() / 60
            
            if gap_minutes > max_gap_minutes:
                gaps_found.append({
                    "start": prev_ts.isoformat(),
                    "end": current_ts.isoformat(),
                    "gap_minutes": int(gap_minutes),
                })
            
            prev_ts = current_ts
    
    # Queue backfills for gaps
    for gap in gaps_found[:10]:  # Limit to 10 gaps per run
        backfill_historical_candles.delay(
            symbol=symbol,
            exchange_id=exchange_id,
            timeframe=timeframe,
            days=1,  # Small window
            start_from=gap["start"],
        )
    
    return {
        "status": "gaps_detected",
        "symbol": symbol_db,
        "gaps_found": len(gaps_found),
        "gaps_queued": min(10, len(gaps_found)),
        "gaps": gaps_found[:10],
    }


@celery_app.task
def fetch_and_store_coin_list():
    """
    Fetches and stores the list of all coins from CoinGecko.
    """
    cg = CoinGeckoConnector()
    all_coins = []
    per_page = 250
    # CoinGecko `coins/markets` is capped per page; paginate until empty.
    for page in range(1, 51):
        batch = cg.get_all_coins(per_page=per_page, page=page)
        if not batch:
            break
        all_coins.extend(batch)

    with session_scope() as db:
        for coin_data in all_coins:
            coin = Coin(
                id=coin_data.get("id"),
                symbol=coin_data.get("symbol"),
                name=coin_data.get("name"),
                market_cap_rank=coin_data.get("market_cap_rank"),
                image=coin_data.get("image"),
            )
            db.merge(coin)

    return f"Successfully ingested {len(all_coins)} coins."


@celery_app.task
def fetch_and_store_news(query: str = 'crypto'):
    """
    Fetches and stores news for a given query.
    """
    # Optional plugin: deliberately not implemented in the zero-cost core.
    return f"News ingestion is disabled in the zero-cost core (query={query!r})."

