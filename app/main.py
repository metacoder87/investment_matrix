from __future__ import annotations

from contextlib import asynccontextmanager
import json
from datetime import datetime, timedelta, timezone
import asyncio
import os
import logging

import pandas as pd
from celery.result import AsyncResult
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analysis import add_technical_indicators
from app.analysis_quant import calculate_risk_metrics
from app.config import settings
from app.services.backfill import StartupGapFiller, bootstrap_universe
from app.services.asset_status import build_signal_status
from app.services.price_selection import resolve_price_exchange
from app.services.market_resolution import configured_exchange_priority
from app.connectors.fundamental import CoinGeckoConnector
from app.connectors.sentiment import Sentiment
from app.connectors.news_api import NewsConnector
from app.connectors.coinmarketcap import CoinMarketCapConnector
from app.connectors.coinpaprika import CoinPaprikaConnector
from app.connectors.financialmodelingprep import FinancialModelingPrepConnector
from app.connectors.newsdata_io import NewsDataIoConnector
from app.redis_client import redis_client
from app.models.market import MarketTrade
from app.models.imports import ImportRun
from app.models.instrument import Coin, Price
from app.models.research import AssetDataStatus
from app.models.ticks import Asset, Tick
from celery_app import celery_app
from app.signals.engine import SignalEngine
from app.services.data_quality import detect_gaps_data
from database import get_db, init_db


logger = logging.getLogger("cryptoinsight.main")


def get_coingecko_connector() -> CoinGeckoConnector:
    return CoinGeckoConnector()

def get_news_connector() -> NewsConnector:
    return NewsConnector()

def get_coinmarketcap_connector() -> CoinMarketCapConnector:
    return CoinMarketCapConnector()

def get_coinpaprika_connector() -> CoinPaprikaConnector:
    return CoinPaprikaConnector()

def get_fmp_connector() -> FinancialModelingPrepConnector:
    return FinancialModelingPrepConnector()

def get_newsdata_connector() -> NewsDataIoConnector:
    return NewsDataIoConnector()

def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("🚀 CryptoInsight starting up...")
        
        # Initialize database
        init_db()
        
        # Run bootstrap in background (non-blocking)
        if os.getenv("PYTEST_CURRENT_TEST") is None:
            logger.info("📊 Triggering universe bootstrap...")
            asyncio.create_task(bootstrap_universe())
            
            # Also run startup gap filler for ongoing maintenance
            await StartupGapFiller.run_startup_check()
        
        yield
        
        logger.info("👋 CryptoInsight shutting down...")

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.API_PREFIX}/openapi.json",
    )

    from fastapi.middleware.cors import CORSMiddleware

    # Parse allowed origins from environment
    allowed_origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]
    
    logger.debug("CORS Middleware configured with allow_origins=%s", allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix=settings.API_PREFIX)
    
    from app.routers import backtest, crew, imports, paper_trading, portfolio, research, system, auth
    api.include_router(portfolio.router)
    api.include_router(system.router)
    api.include_router(imports.router)
    api.include_router(backtest.router)
    api.include_router(paper_trading.router)
    api.include_router(auth.router)
    api.include_router(research.router)
    api.include_router(research.market_router)
    api.include_router(research.ops_router)
    api.include_router(crew.router)

    @api.get("/health", tags=["Meta"])
    async def health():
        return {"status": "ok"}

    # --- Ingestion Endpoints (Celery-triggered) ---
    @api.post("/ingest/prices/{symbol:path}", status_code=202, tags=["Ingestion"])
    async def start_price_ingestion(
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        exchange: str = settings.PRIMARY_EXCHANGE,
    ):
        task = celery_app.send_task(
            "celery_worker.tasks.ingest_historical_data",
            args=[symbol, timeframe, limit],
            kwargs={"exchange_id": exchange},
        )
        return {"message": "Price data ingestion task started.", "task_id": task.id}

    @api.post("/ingest/coins", status_code=202, tags=["Ingestion"])
    async def start_coin_list_ingestion():
        task = celery_app.send_task("celery_worker.tasks.fetch_and_store_coin_list")
        return {"message": "Coin list ingestion task started.", "task_id": task.id}

    @api.get("/ingest/status/{task_id}", tags=["Ingestion"])
    async def get_task_status(task_id: str):
        task_result = AsyncResult(task_id, app=celery_app)
        return {"task_id": task_id, "status": task_result.status, "result": task_result.result}

    # --- Backfill Endpoints ---
    @api.post("/backfill/{exchange}/{symbol:path}", status_code=202, tags=["Ingestion"])
    async def start_backfill(
        exchange: str,
        symbol: str,
        timeframe: str = Query(default="1m", description="Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d)"),
        days: int = Query(default=7, ge=1, le=90, description="Number of days to backfill"),
    ):
        """
        Start a historical data backfill task for a symbol.
        
        Fetches OHLCV candles from the specified exchange and stores them in the database.
        """
        task = celery_app.send_task(
            "celery_worker.tasks.backfill_historical_candles",
            kwargs={
                "symbol": symbol,
                "exchange_id": exchange.lower(),
                "timeframe": timeframe,
                "days": days,
            },
        )
        return {
            "message": f"Backfill started for {symbol} on {exchange}",
            "task_id": task.id,
            "params": {"exchange": exchange, "symbol": symbol, "timeframe": timeframe, "days": days},
        }

    @api.post("/backfill/universe", status_code=202, tags=["Ingestion"])
    async def start_universe_backfill(
        exchange: str = Query(default=settings.PRIMARY_EXCHANGE, description="Exchange to fetch from"),
        days: int = Query(default=7, ge=1, le=30, description="Days to backfill"),
    ):
        """
        Start backfill for the core universe of trading pairs (BTC, ETH, SOL, etc.)
        """
        task = celery_app.send_task(
            "celery_worker.tasks.backfill_core_universe",
            kwargs={"exchange_id": exchange.lower(), "days": days},
        )
        return {"message": "Universe backfill started", "task_id": task.id}

    @api.get("/backfill/gaps/{symbol:path}", tags=["Ingestion"])
    async def detect_gaps(
        symbol: str,
        exchange: str = Query(default=settings.PRIMARY_EXCHANGE),
        timeframe: str = Query(default="1m"),
    ):
        """
        Detect and optionally fill gaps in historical data for a symbol.
        """
        task = celery_app.send_task(
            "celery_worker.tasks.detect_and_fill_gaps",
            kwargs={
                "symbol": symbol,
                "exchange_id": exchange.lower(),
                "timeframe": timeframe,
            },
        )
        return {"message": f"Gap detection started for {symbol}", "task_id": task.id}


    # --- Data Endpoints ---

    @api.get("/coins", tags=["Data"])
    async def get_coins_list(
        background_tasks: BackgroundTasks,
        cg: CoinGeckoConnector = Depends(get_coingecko_connector),
        db: Session = Depends(get_db),
        limit: int = Query(default=500, ge=1, le=5000, description="Max coins to return."),
        offset: int = Query(default=0, ge=0, description="Pagination offset."),
        search: str | None = Query(default=None, description="Filter by symbol or name."),
        source: str = Query(default="auto", description="auto, db, coingecko"),
        exchange: str = Query(default="auto", description="auto or a specific exchange id for signal data."),
        analyzable_only: bool = Query(default=False, description="Only return assets suitable for default signals."),
    ):
        """
        Returns coins from the local DB when available, with a CoinGecko fallback.

        When DB is empty and source=auto, trigger ingestion and fall back to CoinGecko.
        """
        source_key = (source or "auto").strip().lower()
        if source_key not in {"auto", "db", "coingecko"}:
            raise HTTPException(status_code=400, detail="source must be auto, db, or coingecko")

        if source_key in {"auto", "db"}:
            query = db.query(Coin)
            if search:
                like = f"%{search.strip()}%"
                query = query.filter(Coin.symbol.ilike(like) | Coin.name.ilike(like))

            total = query.count()
            if total > 0:
                rank_order = func.coalesce(Coin.market_cap_rank, 999999)
                rows = (
                    query.order_by(rank_order.asc(), Coin.symbol.asc())
                    .offset(offset)
                    .limit(limit)
                    .all()
                )

                symbols_base = []
                for c in rows:
                    s = (c.symbol or "").strip().upper().replace("/", "-")
                    if s:
                        symbols_base.append(s)

                requested_exchange = (exchange or "auto").strip().lower()
                price_exchange = (
                    requested_exchange
                    if requested_exchange and requested_exchange != "auto"
                    else _select_exchange_for_symbols(db, symbols_base)
                )

                latest_sub = (
                    db.query(
                        Price.symbol.label("symbol"),
                        func.max(Price.timestamp).label("max_ts"),
                    )
                    .filter(Price.exchange == price_exchange)
                    .group_by(Price.symbol)
                    .subquery()
                )

                latest_rows = (
                    db.query(Price.symbol, Price.close)
                    .join(
                        latest_sub,
                        (Price.symbol == latest_sub.c.symbol)
                        & (Price.timestamp == latest_sub.c.max_ts)
                        & (Price.exchange == price_exchange),
                    )
                    .all()
                )
                latest_price = {
                    (symbol or "").upper(): float(close) if close is not None else None
                    for symbol, close in latest_rows
                }

                # --- NEW: Fetch Featured Analysis (Signals/RSI) Efficiently ---
                # Key format from get_trading_signal: f"signal:{exchange_key}:{symbol}:{lookback}:{latest_ts}"
                # We'll rely on redis cache inside generation if possible, but here we run the engine batch.
                
                # Symbols to fetch (already normalized for exchange? No, these come from DB Coin/Gecko)
                # DB Symbols are like "BTC", "ETH". But Price needs "BTC-USD".
                # We inferred that logic in backfill, we do similar here.
                # Heuristic: If symbol has no dash, append -USD for the signal check
                symbols_page = []
                for c in rows:
                    s = (c.symbol or "").strip().upper().replace("/", "-")
                    s = StartupGapFiller._normalize_symbol_for_exchange(s, price_exchange)
                    symbols_page.append(s)

                price_stat_rows = (
                    db.query(
                        Price.symbol,
                        func.count(Price.id).label("row_count"),
                        func.max(Price.timestamp).label("latest_ts"),
                    )
                    .filter(Price.exchange == price_exchange, Price.symbol.in_(symbols_page))
                    .group_by(Price.symbol)
                    .all()
                    if symbols_page
                    else []
                )
                price_stats = {
                    row.symbol: {
                        "row_count": int(row.row_count or 0),
                        "latest_ts": row.latest_ts,
                    }
                    for row in price_stat_rows
                }

                status_rows = (
                    db.query(AssetDataStatus)
                    .filter(
                        AssetDataStatus.exchange.in_([price_exchange, "auto"]),
                        AssetDataStatus.symbol.in_(symbols_page),
                    )
                    .all()
                    if symbols_page
                    else []
                )
                status_map = {(row.exchange, row.symbol): row for row in status_rows}

                analysis_map = {}
                
                # Run batch signal generation
                # We limit lookback to 60 candles (enough for RSI/SMA50) for speed in this list view
                # Using asyncio.to_thread to not block the event loop
                # We also set a hard timeout of 5 seconds. If signals take too long, we return list without them.
                # Signals Caching Logic
                signals_cache_key = f"signals:batch:v2:{price_exchange}:{offset}:{limit}"
                cached_signals = None
                try:
                    raw_signals = await redis_client.get(signals_cache_key)
                    if raw_signals:
                        cached_signals = json.loads(raw_signals)
                except Exception:
                    pass

                if cached_signals:
                    analysis_map = cached_signals
                else:
                    try:
                        engine = SignalEngine(db)
                        exchange_map = {sym: price_exchange for sym in symbols_page}
                        batch_signals = await asyncio.wait_for(
                            asyncio.to_thread(
                                engine.generate_signals_batch,
                                symbols_page,
                                exchange_map,
                                60,
                                False,
                            ),
                            timeout=20.0
                        )
                        
                        # Serialize for Cache & Map
                        temp_map = {}
                        for sig in batch_signals:
                            # Map back to symbol. Note: Signal returns normalized symbol e.g. BTC-USD
                            # We store by symbol key directly
                            temp_map[sig.symbol] = {
                                "signal": sig.signal_type.value.upper().replace("_", " "), # STRONG BUY
                                "rsi": sig.indicators.get("rsi"),
                                "confidence": sig.confidence
                            }
                        
                        analysis_map = temp_map
                        
                        # Save to Cache
                        try:
                            await redis_client.setex(signals_cache_key, 300, json.dumps(analysis_map))
                        except Exception as e:
                            logger.warning("Failed to cache signals: %s", e)

                    except asyncio.TimeoutError:
                        logger.warning(
                            "Batch signal generation timed out for %d coins. Returning partial data.",
                            len(symbols_page),
                        )
                        # Do not fail request, just show empty signals
                    except Exception as e:
                        logger.warning("Batch signal error: %s", e)
                        pass

                payload = []
                for coin in rows:
                    price_val = latest_price.get((coin.symbol or "").upper())
                    if price_val is None and coin.current_price is not None:
                        price_val = float(coin.current_price)
                        
                    # Resolve Analysis from Map
                    key = (coin.symbol or "").strip().upper().replace("/", "-")
                    key = StartupGapFiller._normalize_symbol_for_exchange(key, price_exchange)
                    
                    analysis_data = analysis_map.get(key, {})
                    stats = price_stats.get(key, {"row_count": 0, "latest_ts": None})
                    status_record = status_map.get((price_exchange, key)) or status_map.get(("auto", key))
                    signal_status = build_signal_status(
                        exchange=price_exchange,
                        symbol=key,
                        name=coin.name,
                        row_count=stats["row_count"],
                        latest_candle_at=stats["latest_ts"],
                        status_record=status_record,
                        has_signal=bool(analysis_data.get("signal")),
                    )
                    signal_is_displayable = signal_status["status"] in {"ready", "stale"}

                    if analyzable_only and signal_status["status"] in {
                        "not_applicable",
                        "unsupported_market",
                    }:
                        continue

                    payload.append(
                        {
                            "id": coin.id,
                            "symbol": coin.symbol,
                            "name": coin.name,
                            "image": coin.image,
                            "market_cap_rank": coin.market_cap_rank,
                            "market_cap": float(coin.market_cap) if coin.market_cap is not None else None,
                            "current_price": price_val,
                            "price_change_percentage_24h": coin.price_change_percentage_24h,
                            "last_updated": coin.last_updated.isoformat() if coin.last_updated else None,
                            "analysis": {
                                "rsi": analysis_data.get("rsi") if signal_is_displayable else None,
                                "signal": analysis_data.get("signal") if signal_is_displayable else None,
                                "confidence": analysis_data.get("confidence") if signal_is_displayable else None,
                                "status": signal_status["status"],
                                "reason": signal_status["reason"],
                            },
                            "data_status": signal_status,
                        }
                    )
                return payload

            if source_key == "db":
                return []

            if _should_enqueue_celery():
                try:
                    celery_app.send_task("celery_worker.tasks.fetch_and_store_coin_list")
                except Exception:
                    pass

        cache_key = "coins_list_v2"
        refresh_interval = 600  # 10 minutes

        async def _refresh_cache():
            try:
                new_coins = await asyncio.to_thread(cg.get_all_coins, per_page=50, page=1)
                if new_coins:
                    cache_value = {
                        "timestamp": datetime.now(timezone.utc).timestamp(),
                        "data": new_coins,
                    }
                    try:
                        await redis_client.setex(cache_key, 86400, json.dumps(cache_value))
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("Background coin refresh failed: %s", e)

        try:
            raw = await redis_client.get(cache_key)
        except Exception:
            raw = None

        if raw:
            try:
                cached = json.loads(raw)
                if isinstance(cached, list):
                    data = cached
                    age = 999999
                else:
                    data = cached.get("data", [])
                    ts = cached.get("timestamp", 0)
                    age = datetime.now(timezone.utc).timestamp() - ts

                if age > refresh_interval:
                    asyncio.create_task(_refresh_cache())

                return data
            except Exception:
                pass

        coins = await asyncio.to_thread(cg.get_all_coins, per_page=50, page=1)
        if coins:
            cache_value = {
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "data": coins,
            }
            try:
                await redis_client.setex(cache_key, 86400, json.dumps(cache_value))
            except Exception:
                pass
        return coins or []

    @api.get("/coins/search", tags=["Data"])
    async def search_coins(
        q: str = Query(..., description="Search query for coin name or symbol"),
        cg: CoinGeckoConnector = Depends(get_coingecko_connector),
        limit: int = Query(default=20, ge=1, le=100, description="Max results to return"),
    ):
        """
        Search for coins by name or symbol using CoinGecko API.
        Returns coins that are not yet in the local database.
        """
        try:
            # Get all coins from CoinGecko
            all_coins = await asyncio.to_thread(cg.get_all_coins, per_page=250, page=1)
            
            if not all_coins:
                return []
            
            # Filter by search query
            query_lower = q.lower().strip()
            matching_coins = [
                coin for coin in all_coins
                if query_lower in (coin.get("symbol", "").lower()) or 
                   query_lower in (coin.get("name", "").lower())
            ]
            
            # Return limited results
            return matching_coins[:limit]
            
        except Exception as e:
            logger.error(f"Coin search failed: {e}")
            raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    @api.post("/coins/add", tags=["Data"])
    async def add_coin_to_tracking(
        payload: dict,
        db: Session = Depends(get_db),
    ):
        """
        Add a coin to tracking database and trigger historical data backfill.
        
        Payload: {"coingecko_id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"}
        """
        coingecko_id = payload.get("id") or payload.get("coingecko_id")
        symbol = payload.get("symbol", "").upper()
        name = payload.get("name", "")
        
        if not coingecko_id or not symbol:
            raise HTTPException(status_code=400, detail="coingecko_id and symbol are required")
        
        try:
            # Check if coin already exists
            existing = db.query(Coin).filter(Coin.symbol == symbol).first()
            
            if existing:
                return {
                    "message": f"{symbol} already exists in database",
                    "coin_id": existing.id,
                    "existed": True
                }
            
            # Insert new coin
            new_coin = Coin(
                id=coingecko_id,
                symbol=symbol,
                name=name,
                market_cap_rank=None,  # Will be updated by next coin list fetch
            )
            db.add(new_coin)
            db.commit()
            db.refresh(new_coin)
            
            logger.info(f"Added new coin to tracking: {symbol} ({name})")
            
            # Trigger backfill for this coin
            exchange = "auto"
            symbol_pair = symbol
            
            backfill_task = celery_app.send_task(
                "celery_worker.tasks.backfill_historical_candles",
                kwargs={
                    "symbol": symbol_pair,
                    "exchange_id": exchange.lower(),
                    "days": 7,
                    "timeframe": "1m"
                }
            )
            
            return {
                "message": f"Successfully added {symbol} to tracking",
                "coin_id": new_coin.id,
                "existed": False,
                "backfill_task_id": backfill_task.id
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to add coin {symbol}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to add coin: {str(e)}")

    @api.get("/market/latest/{exchange}/{symbol:path}", tags=["Data"])
    async def get_latest_tick_for_exchange(exchange: str, symbol: str):
        exchange = exchange.strip().lower()
        symbol = symbol.strip().upper()
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            symbol = f"{base}-{quote}"
        if exchange == "binance" and symbol.endswith("-USD"):
            symbol = f"{symbol[:-4]}-USDT"
        raw = await redis_client.get(f"latest:{exchange}:{symbol}")
        if not raw:
            raise HTTPException(status_code=404, detail="No live data yet for this exchange/symbol.")
        return json.loads(raw)

    @api.get("/market/latest/{symbol:path}", tags=["Data"])
    async def get_latest_tick(symbol: str):
        raw = await redis_client.get(f"latest:{symbol}")
        if not raw:
            raise HTTPException(status_code=404, detail="No live data yet for this symbol.")
        return json.loads(raw)

    @api.get("/exchanges", tags=["Meta"])
    async def list_exchanges():
        """
        Returns exchanges supported by the current stack.

        - `streaming_supported`: exchanges implemented for live trade streaming.
        - `ccxt_supported`: all exchanges available via CCXT (REST polling/backfill) in principle.
        """
        try:
            import ccxt  # local import to keep FastAPI import time light

            ccxt_supported = list(getattr(ccxt, "exchanges", []))
        except Exception:
            ccxt_supported = []

        return {
            "streaming_supported": ["coinbase", "binance", "kraken"],
            "ccxt_supported": ccxt_supported,
        }

    @api.get("/market/trades/{symbol:path}", tags=["Data"])
    async def get_recent_trades(
        symbol: str,
        db: Session = Depends(get_db),
        exchange: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ):
        """
        Returns recent persisted tick trades from TimescaleDB.
        """
        limit = max(1, min(limit, 5000))

        symbol = symbol.strip().upper()
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            symbol = f"{base}-{quote}"

        if exchange:
            exchange = exchange.strip().lower()
            if exchange == "binance" and symbol.endswith("-USD"):
                symbol = f"{symbol[:-4]}-USDT"

        if since and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        if until and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if since and until and since > until:
            raise HTTPException(status_code=400, detail="Invalid time range: since must be <= until.")

        query = db.query(MarketTrade).filter(MarketTrade.symbol == symbol)
        if exchange:
            query = query.filter(MarketTrade.exchange == exchange)
        if since:
            query = query.filter(MarketTrade.timestamp >= since)
        if until:
            query = query.filter(MarketTrade.timestamp <= until)
        rows = query.order_by(MarketTrade.timestamp.desc()).limit(limit).all()

        # Return ascending time for charting.
        result = []
        for row in reversed(rows):
            result.append(
                {
                    "exchange": row.exchange,
                    "symbol": row.symbol,
                    "timestamp": row.timestamp.isoformat(),
                    "receipt_timestamp": row.receipt_timestamp.isoformat()
                    if row.receipt_timestamp
                    else None,
                    "price": float(row.price),
                    "amount": float(row.amount),
                    "side": row.side,
                }
            )
        return result


    def _to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _normalize_dash_symbol(symbol: str) -> str:
        symbol = symbol.strip().upper()
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            symbol = f"{base}-{quote}"
        return symbol

    def _normalize_symbol_for_exchange(exchange: str | None, symbol: str) -> str:
        exchange = (exchange or "").strip().lower()
        if not exchange:
            priority = _priority_exchanges()
            exchange = priority[0] if priority else ""
        symbol = _normalize_dash_symbol(symbol)
        if exchange == "binance" and symbol.endswith("-USD"):
            return f"{symbol[:-4]}-USDT"
        if exchange in {"coinbase", "kraken"} and "-" not in symbol:
            return f"{symbol}-USD"
        return symbol

    
    def _priority_exchanges() -> list[str]:
        return configured_exchange_priority()

    def _select_exchange_for_symbols(db: Session, symbols: list[str]) -> str:
        priority = _priority_exchanges()
        if not priority:
            return settings.PRIMARY_EXCHANGE.strip().lower() or "kraken"
        for ex in priority:
            normalized = [_normalize_symbol_for_exchange(ex, s) for s in symbols if s]
            if not normalized:
                continue
            hit = (
                db.query(Price.symbol)
                .filter(Price.exchange == ex, Price.symbol.in_(normalized))
                .limit(1)
                .first()
            )
            if hit:
                return ex
        return priority[0]

    def _resolve_asset_id(db: Session, exchange: str, symbol: str) -> int | None:
        return (
            db.query(Asset.id)
            .filter(Asset.exchange == exchange, Asset.symbol == symbol)
            .scalar()
        )

    def _choose_bucket_seconds(range_seconds: float, max_points: int) -> int:
        max_points = max(1, max_points)
        target = max(1.0, range_seconds / max_points)
        candidates = [
            1,
            2,
            5,
            10,
            15,
            30,
            60,
            120,
            300,
            600,
            900,
            1800,
            3600,
            7200,
            14400,
            86400,
        ]
        for c in candidates:
            if c >= target:
                return c
        return candidates[-1]

    def _parse_timeframe_seconds(timeframe: str) -> int:
        raw = (timeframe or "").strip().lower()
        if not raw:
            raise ValueError("timeframe is required")

        unit = raw[-1]
        if unit not in {"s", "m", "h", "d"}:
            raise ValueError(f"Unsupported timeframe={timeframe!r} (use s/m/h/d, e.g. 15m)")
        try:
            value = int(raw[:-1])
        except Exception as e:
            raise ValueError(f"Unsupported timeframe={timeframe!r} (expected e.g. 15m)") from e
        if value <= 0:
            raise ValueError(f"Unsupported timeframe={timeframe!r} (must be > 0)")

        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        seconds = value * multiplier
        if seconds < 1:
            raise ValueError(f"Unsupported timeframe={timeframe!r}")
        return seconds

    def _should_enqueue_celery() -> bool:
        return os.getenv("PYTEST_CURRENT_TEST") is None

    def _align_bucket_time(dt: datetime, bucket_seconds: int) -> datetime:
        epoch = int(dt.timestamp() // bucket_seconds) * bucket_seconds
        return datetime.fromtimestamp(epoch, tz=timezone.utc)

    def _is_recent_rollup_window(end_dt: datetime) -> bool:
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - end_dt <= timedelta(minutes=5)

    def _query_agg_series(
        db: Session,
        *,
        asset_id: int,
        start_dt: datetime,
        end_dt: datetime,
        bucket_seconds: int,
        view_name: str,
        view_bucket_seconds: int,
    ) -> tuple[list[dict], int]:
        effective_bucket = max(bucket_seconds, view_bucket_seconds)
        bucket_interval = f"{effective_bucket} seconds"
        sql = text(
            f"""
            SELECT
              time_bucket(CAST(:bucket AS interval), bucket) AS bucket,
              AVG(close) AS price,
              SUM(volume) AS volume,
              SUM(trades) AS trades
            FROM {view_name}
            WHERE asset_id = :asset_id
              AND bucket >= :start
              AND bucket <= :end
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )
        try:
            rows = (
                db.execute(
                    sql,
                    {
                        "bucket": bucket_interval,
                        "asset_id": asset_id,
                        "start": start_dt,
                        "end": end_dt,
                    },
                )
                .mappings()
                .all()
            )
        except Exception:
            return [], bucket_seconds

        points: list[dict] = []
        for row in rows:
            bucket = row.get("bucket")
            price = row.get("price")
            volume = row.get("volume")
            trades = row.get("trades")
            if bucket is None or price is None:
                continue
            points.append(
                {
                    "timestamp": bucket.isoformat(),
                    "price": float(price),
                    "volume": float(volume) if volume is not None else 0.0,
                    "trades": int(trades) if trades is not None else 0,
                }
            )
        return points, effective_bucket

    def _query_agg_candles(
        db: Session,
        *,
        asset_id: int,
        start_dt: datetime,
        end_dt: datetime,
        bucket_seconds: int,
        view_name: str,
        view_bucket_seconds: int,
    ) -> tuple[list[dict], int]:
        effective_bucket = max(bucket_seconds, view_bucket_seconds)
        bucket_interval = f"{effective_bucket} seconds"
        sql = text(
            f"""
            SELECT
              time_bucket(CAST(:bucket AS interval), bucket) AS bucket,
              first(open, bucket) AS open,
              max(high) AS high,
              min(low) AS low,
              last(close, bucket) AS close,
              SUM(volume) AS volume,
              SUM(trades) AS trades
            FROM {view_name}
            WHERE asset_id = :asset_id
              AND bucket >= :start
              AND bucket <= :end
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )
        try:
            rows = (
                db.execute(
                    sql,
                    {
                        "bucket": bucket_interval,
                        "asset_id": asset_id,
                        "start": start_dt,
                        "end": end_dt,
                    },
                )
                .mappings()
                .all()
            )
        except Exception:
            return [], bucket_seconds

        candles: list[dict] = []
        for row in rows:
            bucket = row.get("bucket")
            open_p = row.get("open")
            high_p = row.get("high")
            low_p = row.get("low")
            close_p = row.get("close")
            volume = row.get("volume")
            trades = row.get("trades")
            if bucket is None or open_p is None or high_p is None or low_p is None or close_p is None:
                continue
            candles.append(
                {
                    "timestamp": bucket.isoformat(),
                    "open": float(open_p),
                    "high": float(high_p),
                    "low": float(low_p),
                    "close": float(close_p),
                    "volume": float(volume) if volume is not None else 0.0,
                    "trades": int(trades) if trades is not None else 0,
                }
            )
        return candles, effective_bucket

    @api.get("/market/series/{exchange}/{symbol:path}", tags=["Data"])
    async def get_market_series(
        exchange: str,
        symbol: str,
        db: Session = Depends(get_db),
        start: datetime | None = Query(default=None, description="Start time (ISO 8601). Defaults to 1h ago."),
        end: datetime | None = Query(default=None, description="End time (ISO 8601). Defaults to now (UTC)."),
        max_points: int = Query(default=2000, ge=100, le=5000, description="Max points returned (server will bucket)."),
    ):
        """
        Returns a downsampled market price series for an exchange+symbol over a time range.

        Uses TimescaleDB `time_bucket` on Postgres; falls back to Python bucketing for SQLite/tests.
        """
        exchange = exchange.strip().lower()
        base_symbol = symbol
        if exchange == "auto":
            base_symbol = _normalize_dash_symbol(symbol)
            exchange = _select_exchange_for_symbols(db, [base_symbol])
        symbol = _normalize_symbol_for_exchange(exchange, base_symbol)

        # Trigger live subscription for this symbol when possible.
        try:
            await redis_client.publish(
                "streamer:commands",
                json.dumps({"action": "subscribe", "symbol": symbol, "exchange": exchange}),
            )
        except Exception:
            pass

        end_dt = _to_utc(end) if end else datetime.now(timezone.utc)
        start_dt = _to_utc(start) if start else end_dt - timedelta(hours=1)
        if start_dt > end_dt:
            raise HTTPException(status_code=400, detail="Invalid time range: start must be <= end.")

        range_seconds = max(1.0, (end_dt - start_dt).total_seconds())
        bucket_seconds = _choose_bucket_seconds(range_seconds, max_points)

        dialect = db.get_bind().dialect.name
        points: list[dict] = []
        asset_id = _resolve_asset_id(db, exchange, symbol)

        if dialect == "postgresql" and asset_id:
            bucket_interval = f"{bucket_seconds} seconds"
            sql = text(
                """
                SELECT
                  time_bucket(CAST(:bucket AS interval), time) AS bucket,
                  AVG(price) AS price,
                  SUM(volume) AS volume,
                  COUNT(*) AS trades
                FROM ticks
                WHERE asset_id = :asset_id
                  AND time >= :start
                  AND time <= :end
                GROUP BY bucket
                ORDER BY bucket ASC
                """
            )
            try:
                rows = (
                    db.execute(
                        sql,
                        {
                            "bucket": bucket_interval,
                            "asset_id": asset_id,
                            "start": start_dt,
                            "end": end_dt,
                        },
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    bucket = row.get("bucket")
                    price = row.get("price")
                    volume = row.get("volume")
                    trades = row.get("trades")
                    if bucket is None or price is None:
                        continue
                    points.append(
                        {
                            "timestamp": bucket.isoformat(),
                            "price": float(price),
                            "volume": float(volume) if volume is not None else 0.0,
                            "trades": int(trades) if trades is not None else 0,
                        }
                    )
            except Exception:
                points = []

        if not points and dialect == "postgresql" and asset_id:
            for view_name, view_bucket in (
                ("ticks_1s", 1),
                ("ticks_3s", 3),
                ("ticks_5s", 5),
                ("ticks_7s", 7),
            ):
                points, candidate_bucket = _query_agg_series(
                    db,
                    asset_id=asset_id,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    bucket_seconds=bucket_seconds,
                    view_name=view_name,
                    view_bucket_seconds=view_bucket,
                )
                if points:
                    bucket_seconds = candidate_bucket
                    break

        if not points and dialect == "postgresql":
            bucket_interval = f"{bucket_seconds} seconds"
            sql = text(
                """
                SELECT
                  time_bucket(CAST(:bucket AS interval), timestamp) AS bucket,
                  AVG(price) AS price,
                  SUM(amount) AS volume,
                  COUNT(*) AS trades
                FROM market_trades
                WHERE exchange = :exchange
                  AND symbol = :symbol
                  AND timestamp >= :start
                  AND timestamp <= :end
                GROUP BY bucket
                ORDER BY bucket ASC
                """
            )
            try:
                rows = (
                    db.execute(
                        sql,
                        {
                            "bucket": bucket_interval,
                            "exchange": exchange,
                            "symbol": symbol,
                            "start": start_dt,
                            "end": end_dt,
                        },
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    bucket = row.get("bucket")
                    price = row.get("price")
                    volume = row.get("volume")
                    trades = row.get("trades")
                    if bucket is None or price is None:
                        continue
                    points.append(
                        {
                            "timestamp": bucket.isoformat(),
                            "price": float(price),
                            "volume": float(volume) if volume is not None else 0.0,
                            "trades": int(trades) if trades is not None else 0,
                        }
                    )
            except Exception:
                # If Timescale functions are unavailable, fall back to Python bucketing.
                points = []

        if not points and asset_id:
            rows = (
                db.query(Tick)
                .filter(
                    Tick.asset_id == asset_id,
                    Tick.time >= start_dt,
                    Tick.time <= end_dt,
                )
                .order_by(Tick.time.asc())
                .all()
            )
            buckets: dict[int, dict] = {}
            for row in rows:
                ts = row.time
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                bucket_idx = int((ts - start_dt).total_seconds() // bucket_seconds)
                item = buckets.get(bucket_idx)
                if item is None:
                    item = {
                        "timestamp": (start_dt + timedelta(seconds=bucket_idx * bucket_seconds)).isoformat(),
                        "sum_price": float(row.price),
                        "count": 1,
                        "volume": float(row.volume),
                    }
                    buckets[bucket_idx] = item
                else:
                    item["sum_price"] += float(row.price)
                    item["count"] += 1
                    item["volume"] += float(row.volume)

            for bucket_idx in sorted(buckets.keys()):
                item = buckets[bucket_idx]
                count = int(item["count"])
                if count <= 0:
                    continue
                points.append(
                    {
                        "timestamp": item["timestamp"],
                        "price": float(item["sum_price"]) / count,
                        "volume": float(item["volume"]),
                        "trades": count,
                    }
                )

        if not points:
            rows = (
                db.query(MarketTrade)
                .filter(
                    MarketTrade.exchange == exchange,
                    MarketTrade.symbol == symbol,
                    MarketTrade.timestamp >= start_dt,
                    MarketTrade.timestamp <= end_dt,
                )
                .order_by(MarketTrade.timestamp.asc())
                .all()
            )
            buckets: dict[int, dict] = {}
            for row in rows:
                ts = row.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                bucket_idx = int((ts - start_dt).total_seconds() // bucket_seconds)
                item = buckets.get(bucket_idx)
                if item is None:
                    item = {
                        "timestamp": (start_dt + timedelta(seconds=bucket_idx * bucket_seconds)).isoformat(),
                        "sum_price": float(row.price),
                        "count": 1,
                        "volume": float(row.amount),
                    }
                    buckets[bucket_idx] = item
                else:
                    item["sum_price"] += float(row.price)
                    item["count"] += 1
                    item["volume"] += float(row.amount)

            for bucket_idx in sorted(buckets.keys()):
                item = buckets[bucket_idx]
                count = int(item["count"])
                if count <= 0:
                    continue
                points.append(
                    {
                        "timestamp": item["timestamp"],
                        "price": float(item["sum_price"]) / count,
                        "volume": float(item["volume"]),
                        "trades": count,
                    }
                )

        return {
            "exchange": exchange,
            "symbol": symbol,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "bucket_seconds": bucket_seconds,
            "points": points,
        }

    @api.get("/market/candles/{exchange}/{symbol:path}", tags=["Data"])
    async def get_market_candles(
        exchange: str,
        symbol: str,
        db: Session = Depends(get_db),
        start: datetime | None = Query(default=None, description="Start time (ISO 8601). Defaults to 1h ago."),
        end: datetime | None = Query(default=None, description="End time (ISO 8601). Defaults to now (UTC)."),
        timeframe: str = Query(default="1m", description="Requested candle timeframe (e.g. 1m, 5m, 1h)."),
        max_points: int = Query(default=2000, ge=100, le=5000, description="Max candles returned (server may coarsen)."),
    ):
        """
        Returns OHLCV candles derived from persisted tick trades in `ticks`.

        - Uses TimescaleDB `time_bucket` + `first/last` on Postgres.
        - Falls back to market_trades and Python aggregation for SQLite/tests.
        """
        exchange = exchange.strip().lower()
        base_symbol = symbol
        if exchange == "auto":
            base_symbol = _normalize_dash_symbol(symbol)
            exchange = _select_exchange_for_symbols(db, [base_symbol])
        symbol = _normalize_symbol_for_exchange(exchange, base_symbol)

        end_dt = _to_utc(end) if end else datetime.now(timezone.utc)
        start_dt = _to_utc(start) if start else end_dt - timedelta(hours=1)
        if start_dt > end_dt:
            raise HTTPException(status_code=400, detail="Invalid time range: start must be <= end.")

        try:
            requested_bucket_seconds = _parse_timeframe_seconds(timeframe)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        range_seconds = max(1.0, (end_dt - start_dt).total_seconds())
        bucket_seconds = max(requested_bucket_seconds, _choose_bucket_seconds(range_seconds, max_points))

        candles: list[dict] = []
        source_used = "none"
        data_resolution = "none"
        dialect = db.get_bind().dialect.name
        asset_id = _resolve_asset_id(db, exchange, symbol)
        if dialect == "postgresql" and asset_id and not _is_recent_rollup_window(end_dt):
            for view_name, view_bucket in (
                ("ticks_5m", 300),
                ("ticks_1m", 60),
            ):
                if bucket_seconds < view_bucket:
                    continue
                candles, candidate_bucket = _query_agg_candles(
                    db,
                    asset_id=asset_id,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    bucket_seconds=bucket_seconds,
                    view_name=view_name,
                    view_bucket_seconds=view_bucket,
                )
                if candles:
                    bucket_seconds = candidate_bucket
                    source_used = view_name
                    data_resolution = "timescale_tick_rollup"
                    break

        if not candles and dialect == "postgresql" and asset_id:
            bucket_interval = f"{bucket_seconds} seconds"
            sql = text(
                """
                SELECT
                  time_bucket(CAST(:bucket AS interval), time) AS bucket,
                  first(price, time) AS open,
                  max(price) AS high,
                  min(price) AS low,
                  last(price, time) AS close,
                  SUM(volume) AS volume,
                  COUNT(*) AS trades
                FROM ticks
                WHERE asset_id = :asset_id
                  AND time >= :start
                  AND time <= :end
                GROUP BY bucket
                ORDER BY bucket ASC
                """
            )
            try:
                rows = (
                    db.execute(
                        sql,
                        {
                            "bucket": bucket_interval,
                            "asset_id": asset_id,
                            "start": start_dt,
                            "end": end_dt,
                        },
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    bucket = row.get("bucket")
                    open_p = row.get("open")
                    high_p = row.get("high")
                    low_p = row.get("low")
                    close_p = row.get("close")
                    volume = row.get("volume")
                    trades = row.get("trades")
                    if bucket is None or open_p is None or high_p is None or low_p is None or close_p is None:
                        continue
                    candles.append(
                        {
                            "timestamp": bucket.isoformat(),
                            "open": float(open_p),
                            "high": float(high_p),
                            "low": float(low_p),
                            "close": float(close_p),
                            "volume": float(volume) if volume is not None else 0.0,
                            "trades": int(trades) if trades is not None else 0,
                        }
                    )
                if candles:
                    source_used = "ticks"
                    data_resolution = "raw_ticks"
            except Exception:
                candles = []

        if not candles and dialect == "postgresql" and asset_id:
            for view_name, view_bucket in (
                ("ticks_1s", 1),
                ("ticks_3s", 3),
                ("ticks_5s", 5),
                ("ticks_7s", 7),
            ):
                candles, candidate_bucket = _query_agg_candles(
                    db,
                    asset_id=asset_id,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    bucket_seconds=bucket_seconds,
                    view_name=view_name,
                    view_bucket_seconds=view_bucket,
                )
                if candles:
                    bucket_seconds = candidate_bucket
                    source_used = view_name
                    data_resolution = "timescale_tick_rollup"
                    break

        if not candles and dialect == "postgresql":
            bucket_interval = f"{bucket_seconds} seconds"
            sql = text(
                """
                SELECT
                  time_bucket(CAST(:bucket AS interval), timestamp) AS bucket,
                  first(price, timestamp) AS open,
                  max(price) AS high,
                  min(price) AS low,
                  last(price, timestamp) AS close,
                  SUM(amount) AS volume,
                  COUNT(*) AS trades
                FROM market_trades
                WHERE exchange = :exchange
                  AND symbol = :symbol
                  AND timestamp >= :start
                  AND timestamp <= :end
                GROUP BY bucket
                ORDER BY bucket ASC
                """
            )
            try:
                rows = (
                    db.execute(
                        sql,
                        {
                            "bucket": bucket_interval,
                            "exchange": exchange,
                            "symbol": symbol,
                            "start": start_dt,
                            "end": end_dt,
                        },
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    bucket = row.get("bucket")
                    open_p = row.get("open")
                    high_p = row.get("high")
                    low_p = row.get("low")
                    close_p = row.get("close")
                    volume = row.get("volume")
                    trades = row.get("trades")
                    if bucket is None or open_p is None or high_p is None or low_p is None or close_p is None:
                        continue
                    candles.append(
                        {
                            "timestamp": bucket.isoformat(),
                            "open": float(open_p),
                            "high": float(high_p),
                            "low": float(low_p),
                            "close": float(close_p),
                            "volume": float(volume) if volume is not None else 0.0,
                            "trades": int(trades) if trades is not None else 0,
                        }
                    )
                if candles:
                    source_used = "market_trades"
                    data_resolution = "compatibility_trades"
            except Exception:
                candles = []

        if not candles and asset_id:
            rows = (
                db.query(Tick)
                .filter(
                    Tick.asset_id == asset_id,
                    Tick.time >= start_dt,
                    Tick.time <= end_dt,
                )
                .order_by(Tick.time.asc())
                .all()
            )
            buckets: dict[int, dict] = {}
            for row in rows:
                ts = row.time
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)

                # Align buckets to epoch boundaries to match time_bucket behavior.
                bucket_epoch = int(ts.timestamp() // bucket_seconds) * bucket_seconds
                item = buckets.get(bucket_epoch)
                price = float(row.price)
                amount = float(row.volume)
                if item is None:
                    buckets[bucket_epoch] = {
                        "timestamp": datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat(),
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": amount,
                        "trades": 1,
                    }
                else:
                    item["high"] = max(float(item["high"]), price)
                    item["low"] = min(float(item["low"]), price)
                    item["close"] = price
                    item["volume"] = float(item["volume"]) + amount
                    item["trades"] = int(item["trades"]) + 1

            for bucket_epoch in sorted(buckets.keys()):
                candles.append(buckets[bucket_epoch])
            if candles:
                source_used = "ticks"
                data_resolution = "raw_ticks"

        if not candles:
            rows = (
                db.query(MarketTrade)
                .filter(
                    MarketTrade.exchange == exchange,
                    MarketTrade.symbol == symbol,
                    MarketTrade.timestamp >= start_dt,
                    MarketTrade.timestamp <= end_dt,
                )
                .order_by(MarketTrade.timestamp.asc())
                .all()
            )
            buckets: dict[int, dict] = {}
            for row in rows:
                ts = row.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)

                # Align buckets to epoch boundaries to match time_bucket behavior.
                bucket_epoch = int(ts.timestamp() // bucket_seconds) * bucket_seconds
                item = buckets.get(bucket_epoch)
                price = float(row.price)
                amount = float(row.amount)
                if item is None:
                    buckets[bucket_epoch] = {
                        "timestamp": datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat(),
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": amount,
                        "trades": 1,
                    }
                else:
                    item["high"] = max(float(item["high"]), price)
                    item["low"] = min(float(item["low"]), price)
                    item["close"] = price
                    item["volume"] = float(item["volume"]) + amount
                    item["trades"] = int(item["trades"]) + 1

            for bucket_epoch in sorted(buckets.keys()):
                candles.append(buckets[bucket_epoch])
            if candles:
                source_used = "market_trades"
                data_resolution = "compatibility_trades"

        # Fallback: query the prices table (used by backfill) if no data in market_trades
        if not candles:
            prices_rows = (
                db.query(Price)
                .filter(
                    Price.exchange == exchange,
                    Price.symbol == symbol,
                    Price.timestamp >= start_dt,
                    Price.timestamp <= end_dt,
                )
                .order_by(Price.timestamp.asc())
                .all()
            )
            buckets = {}
            for row in prices_rows:
                ts = row.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)

                bucket_epoch = int(ts.timestamp() // bucket_seconds) * bucket_seconds
                item = buckets.get(bucket_epoch)
                open_p = float(row.open) if row.open else 0.0
                high_p = float(row.high) if row.high else 0.0
                low_p = float(row.low) if row.low else 0.0
                close_p = float(row.close) if row.close else 0.0
                volume = float(row.volume) if row.volume else 0.0
                if item is None:
                    buckets[bucket_epoch] = {
                        "timestamp": datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat(),
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": volume,
                        "trades": 1,
                    }
                else:
                    # For aggregation, update OHLC properly
                    item["high"] = max(item["high"], high_p)
                    item["low"] = min(item["low"], low_p) if item["low"] > 0 else low_p
                    item["close"] = close_p
                    item["volume"] = item["volume"] + volume
                    item["trades"] = item["trades"] + 1

            for bucket_epoch in sorted(buckets.keys()):
                candles.append(buckets[bucket_epoch])
            if candles:
                source_used = "prices"
                data_resolution = "ohlcv_candles"

        backfill_status = None
        if not candles and _should_enqueue_celery():
            try:
                from celery_worker.tasks import backfill_historical_candles
                range_days = max(1, int((end_dt - start_dt).total_seconds() // 86400) + 1)
                days = min(90, range_days)
                task = backfill_historical_candles.delay(
                    symbol=symbol,
                    exchange_id=exchange,
                    timeframe=timeframe,
                    days=days,
                )
                backfill_status = {"queued": True, "task_id": task.id, "days": days}
            except Exception:
                backfill_status = {"queued": False}

        return {
            "exchange": exchange,
            "symbol": symbol,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "timeframe": timeframe,
            "requested_bucket_seconds": requested_bucket_seconds,
            "bucket_seconds": bucket_seconds,
            "source": source_used,
            "data_resolution": data_resolution,
            "candles": candles,
            "backfill": backfill_status,
        }

    @api.get("/market/coverage/{exchange}/{symbol:path}", tags=["Data"])
    async def get_market_coverage(exchange: str, symbol: str, db: Session = Depends(get_db)):
        """
        Returns what is currently persisted in TimescaleDB for a given exchange+symbol.

        Useful for validating that the writer is storing trades and for estimating how much historic data you have.
        """
        exchange = exchange.strip().lower()
        base_symbol = symbol
        if exchange == "auto":
            base_symbol = _normalize_dash_symbol(symbol)
            exchange = _select_exchange_for_symbols(db, [base_symbol])
        symbol = _normalize_symbol_for_exchange(exchange, base_symbol)
        dialect = db.get_bind().dialect.name
        asset_id = _resolve_asset_id(db, exchange, symbol)

        if asset_id:
            if dialect == "postgresql":
                sql = text(
                    """
                    SELECT
                      min(time) AS first_ts,
                      max(time) AS last_ts,
                      count(*) AS trades
                    FROM ticks
                    WHERE asset_id = :asset_id
                    """
                )
                try:
                    row = (
                        db.execute(sql, {"asset_id": asset_id})
                        .mappings()
                        .one()
                    )
                    first_ts = row.get("first_ts")
                    last_ts = row.get("last_ts")
                    count = row.get("trades")
                except Exception:
                    first_ts = last_ts = count = None
            else:
                first_ts, last_ts, count = (
                    db.query(
                        func.min(Tick.time),
                        func.max(Tick.time),
                        func.count(Tick.id),
                    )
                    .filter(Tick.asset_id == asset_id)
                    .one()
                )

            if count:
                return {
                    "exchange": exchange,
                    "symbol": symbol,
                    "trades": int(count or 0),
                    "first_timestamp": first_ts.isoformat() if first_ts else None,
                    "last_timestamp": last_ts.isoformat() if last_ts else None,
                    "source": "ticks",
                }

            if dialect == "postgresql":
                for view_name, view_bucket in (
                    ("ticks_1s", 1),
                    ("ticks_3s", 3),
                    ("ticks_5s", 5),
                    ("ticks_7s", 7),
                ):
                    try:
                        sql = text(
                            f"""
                            SELECT
                              min(bucket) AS first_ts,
                              max(bucket) AS last_ts,
                              SUM(trades) AS trades
                            FROM {view_name}
                            WHERE asset_id = :asset_id
                            """
                        )
                        row = (
                            db.execute(sql, {"asset_id": asset_id})
                            .mappings()
                            .one()
                        )
                    except Exception:
                        continue

                    count = row.get("trades")
                    if count:
                        return {
                            "exchange": exchange,
                            "symbol": symbol,
                            "trades": int(count or 0),
                            "first_timestamp": row.get("first_ts").isoformat()
                            if row.get("first_ts")
                            else None,
                            "last_timestamp": row.get("last_ts").isoformat()
                            if row.get("last_ts")
                            else None,
                            "source": view_name,
                            "granularity_seconds": view_bucket,
                        }

        first_ts, last_ts, count = (
            db.query(
                func.min(MarketTrade.timestamp),
                func.max(MarketTrade.timestamp),
                func.count(MarketTrade.id),
            )
            .filter(MarketTrade.exchange == exchange, MarketTrade.symbol == symbol)
            .one()
        )

        return {
            "exchange": exchange,
            "symbol": symbol,
            "trades": int(count or 0),
            "first_timestamp": first_ts.isoformat() if first_ts else None,
            "last_timestamp": last_ts.isoformat() if last_ts else None,
            "source": "market_trades",
        }

    @api.get("/market/gaps/{exchange}/{symbol:path}", tags=["Data"])
    async def get_market_gaps(
        exchange: str,
        symbol: str,
        db: Session = Depends(get_db),
        start: datetime | None = Query(default=None, description="Start time (ISO 8601). Defaults to 1h ago."),
        end: datetime | None = Query(default=None, description="End time (ISO 8601). Defaults to now (UTC)."),
        bucket_seconds: int = Query(default=1, ge=1, description="Gap bucket size in seconds."),
        max_points: int = Query(default=5000, ge=100, le=20000, description="Max buckets to evaluate."),
        source: str = Query(
            default="auto",
            description="auto, ticks, ticks_1s, ticks_3s, ticks_5s, ticks_7s, market_trades",
        ),
    ):
        """
        Detects empty buckets (gaps) in the requested time range at a given resolution.

        Note: a gap means "no data recorded in the bucket" at the chosen resolution,
        not necessarily that trades were missing on the exchange.
        """
        exchange = exchange.strip().lower()
        base_symbol = symbol
        if exchange == "auto":
            base_symbol = _normalize_dash_symbol(symbol)
            exchange = _select_exchange_for_symbols(db, [base_symbol])
        symbol = _normalize_symbol_for_exchange(exchange, base_symbol)

        end_dt = _to_utc(end) if end else datetime.now(timezone.utc)
        start_dt = _to_utc(start) if start else end_dt - timedelta(hours=1)
        if start_dt > end_dt:
            raise HTTPException(status_code=400, detail="Invalid time range: start must be <= end.")

        gap_data = detect_gaps_data(
            db,
            exchange=exchange,
            symbol=symbol,
            start_dt=start_dt,
            end_dt=end_dt,
            bucket_seconds=bucket_seconds,
            max_points=max_points,
            source=source,
        )

        return {
            "exchange": exchange,
            "symbol": symbol,
            "source": gap_data["source"],
            "source_granularity_seconds": gap_data["source_granularity_seconds"],
            "start": gap_data["aligned_start"].isoformat(),
            "end": gap_data["aligned_end"].isoformat(),
            "bucket_seconds": bucket_seconds,
            "total_buckets": gap_data["total_buckets"],
            "covered_buckets": gap_data["covered_buckets"],
            "missing_buckets": gap_data["missing_buckets"],
            "gaps": gap_data["gaps"],
        }

    @api.post("/market/gaps/repair/{exchange}/{symbol:path}", tags=["Data"])
    async def repair_market_gaps(
        exchange: str,
        symbol: str,
        db: Session = Depends(get_db),
        start: datetime | None = Query(default=None, description="Start time (ISO 8601). Defaults to 1h ago."),
        end: datetime | None = Query(default=None, description="End time (ISO 8601). Defaults to now (UTC)."),
        bucket_seconds: int = Query(default=1, ge=1, description="Gap bucket size in seconds."),
        max_points: int = Query(default=5000, ge=100, le=20000, description="Max buckets to evaluate."),
        source: str = Query(
            default="auto",
            description="auto, ticks, ticks_1s, ticks_3s, ticks_5s, ticks_7s, market_trades",
        ),
        import_source: str = Query(default="binance_vision", description="binance_vision or dukascopy"),
        kind: str = Query(default="trades", description="Binance Vision kind: trades or aggTrades"),
        store_exchange: str | None = Query(default=None, description="Exchange label to store with imported data."),
        owner_id: str | None = Query(default=None),
        max_ranges: int = Query(default=5, ge=1, le=50),
        dry_run: bool = Query(default=False),
    ):
        """
        Queue backfill jobs for missing buckets using bulk data sources.

        Note: bulk sources are coarse (daily or hourly). Small gaps may still result
        in large data pulls, but idempotency prevents duplicates.
        """
        exchange = exchange.strip().lower()
        base_symbol = symbol
        if exchange == "auto":
            base_symbol = _normalize_dash_symbol(symbol)
            exchange = _select_exchange_for_symbols(db, [base_symbol])
        symbol = _normalize_symbol_for_exchange(exchange, base_symbol)
        import_source = import_source.strip().lower()
        kind = kind.strip()

        end_dt = _to_utc(end) if end else datetime.now(timezone.utc)
        start_dt = _to_utc(start) if start else end_dt - timedelta(hours=1)
        if start_dt > end_dt:
            raise HTTPException(status_code=400, detail="Invalid time range: start must be <= end.")

        gap_data = detect_gaps_data(
            db,
            exchange=exchange,
            symbol=symbol,
            start_dt=start_dt,
            end_dt=end_dt,
            bucket_seconds=bucket_seconds,
            max_points=max_points,
            source=source,
        )

        gap_ranges = gap_data["gaps"]
        if not gap_ranges:
            return {
                "exchange": exchange,
                "symbol": symbol,
                "source": gap_data["source"],
                "gaps": [],
                "planned_tasks": [],
                "queued": False,
                "message": "No gaps detected.",
            }

        if import_source not in {"binance_vision", "dukascopy"}:
            raise HTTPException(status_code=400, detail="Unsupported import_source.")

        enqueue = (not dry_run) and _should_enqueue_celery()
        planned: list[dict] = []

        if import_source == "binance_vision":
            import_symbol = _normalize_symbol_for_exchange("binance", symbol)
            exchange_label = store_exchange or "binance"
            if kind.lower() in {"agg_trades", "aggtrades"}:
                kind = "aggTrades"
            elif kind.lower() != "trades":
                raise HTTPException(status_code=400, detail="kind must be trades or aggTrades")

            for gap_range in gap_ranges[:max_ranges]:
                gap_start = datetime.fromisoformat(gap_range["start"])
                gap_end = datetime.fromisoformat(gap_range["end"])
                inclusive_end = gap_end - timedelta(seconds=1)
                start_date = gap_start.date().isoformat()
                end_date = inclusive_end.date().isoformat()
                params = {
                    "symbol": import_symbol,
                    "exchange": exchange_label,
                    "kind": kind,
                    "start_date": start_date,
                    "end_date": end_date,
                    "owner_id": owner_id,
                }
                planned.append({"task": "import_binance_vision_range", **params})
                if enqueue:
                    celery_app.send_task("celery_worker.tasks.import_binance_vision_range", kwargs=params)

        if import_source == "dukascopy":
            import_symbol = symbol
            exchange_label = store_exchange or "dukascopy"
            for gap_range in gap_ranges[:max_ranges]:
                gap_start = datetime.fromisoformat(gap_range["start"])
                gap_end = datetime.fromisoformat(gap_range["end"])
                params = {
                    "symbol": import_symbol,
                    "exchange": exchange_label,
                    "start_datetime": gap_start.isoformat(),
                    "end_datetime": gap_end.isoformat(),
                    "owner_id": owner_id,
                }
                planned.append({"task": "import_dukascopy_range", **params})
                if enqueue:
                    celery_app.send_task("celery_worker.tasks.import_dukascopy_range", kwargs=params)

        return {
            "exchange": exchange,
            "symbol": symbol,
            "source": gap_data["source"],
            "gaps": gap_ranges[:max_ranges],
            "planned_tasks": planned,
            "queued": enqueue,
            "skipped_gaps": max(0, len(gap_ranges) - max_ranges),
        }

    @api.get("/system/ingestion/health", tags=["System"])
    async def get_ingestion_health(
        db: Session = Depends(get_db),
        exchange: str = Query(default="coinbase"),
        symbols: str | None = Query(default=None, description="Comma-separated symbols (e.g. BTC-USD,ETH-USD)"),
        lookback_hours: int = Query(default=24, ge=1, le=168),
    ):
        exchange = exchange.strip().lower()
        raw_symbols = symbols or settings.CORE_UNIVERSE
        symbol_list = [_normalize_symbol_for_exchange(exchange, s) for s in raw_symbols.split(",") if s.strip()]

        now = datetime.now(timezone.utc)
        redis_ok = True
        latest_stream: dict[str, datetime | None] = {}

        if symbol_list:
            keys = [f"latest:{exchange}:{sym}" for sym in symbol_list]
            try:
                raw_values = await redis_client.mget(keys)
            except Exception:
                redis_ok = False
                raw_values = [None] * len(keys)

            for sym, raw in zip(symbol_list, raw_values):
                if not raw:
                    latest_stream[sym] = None
                    continue
                try:
                    payload = json.loads(raw)
                    ts = payload.get("ts")
                    latest_stream[sym] = (
                        datetime.fromtimestamp(float(ts), tz=timezone.utc) if ts is not None else None
                    )
                except Exception:
                    latest_stream[sym] = None

        symbol_health: list[dict] = []
        for sym in symbol_list:
            asset_id = _resolve_asset_id(db, exchange, sym)
            latest_db = None
            source_used = None
            if asset_id is not None:
                latest_db = (
                    db.query(func.max(Tick.time))
                    .filter(Tick.asset_id == asset_id)
                    .scalar()
                )
                if latest_db:
                    source_used = "ticks"
            if latest_db is None:
                latest_db = (
                    db.query(func.max(MarketTrade.timestamp))
                    .filter(MarketTrade.exchange == exchange, MarketTrade.symbol == sym)
                    .scalar()
                )
                if latest_db:
                    source_used = "market_trades"

            stream_ts = latest_stream.get(sym)
            if latest_db and latest_db.tzinfo is None:
                latest_db = latest_db.replace(tzinfo=timezone.utc)
            stream_lag = (now - stream_ts).total_seconds() if stream_ts else None
            db_lag = (now - latest_db).total_seconds() if latest_db else None

            symbol_health.append(
                {
                    "symbol": sym,
                    "latest_stream_timestamp": stream_ts.isoformat() if stream_ts else None,
                    "latest_db_timestamp": latest_db.isoformat() if latest_db else None,
                    "stream_lag_seconds": stream_lag,
                    "db_lag_seconds": db_lag,
                    "source": source_used,
                }
            )

        cutoff = now - timedelta(hours=lookback_hours)
        import_counts = (
            db.query(ImportRun.status, func.count(ImportRun.id))
            .filter(ImportRun.started_at >= cutoff)
            .group_by(ImportRun.status)
            .all()
        )
        import_summary = {status: count for status, count in import_counts}

        return {
            "checked_at": now.isoformat(),
            "exchange": exchange,
            "redis_ok": redis_ok,
            "symbols": symbol_health,
            "imports": {
                "lookback_hours": lookback_hours,
                "counts": import_summary,
            },
        }

    @api.get("/coin/{symbol:path}/analysis", tags=["Analysis"])
    async def get_coin_analysis(
        symbol: str,
        exchange: str | None = Query(
            default="auto",
            description="Exchange to use (auto or exchange id).",
        ),
        db: Session = Depends(get_db),
    ):
        symbol = _normalize_dash_symbol(symbol)
        exchange_key = resolve_price_exchange(db, symbol, exchange)
        symbol = _normalize_symbol_for_exchange(exchange_key, symbol)
        # 1. Get Latest Timestamp (Lightweight Query)
        latest_ts = db.query(func.max(Price.timestamp)).filter(Price.exchange == exchange_key, Price.symbol == symbol).scalar()
        
        if not latest_ts:
            # Trigger On-Demand Backfill
            from celery_worker.tasks import backfill_historical_candles
            if _should_enqueue_celery():
                try:
                    backfill_historical_candles.delay(symbol=symbol, exchange_id=exchange_key)
                except Exception:
                    pass
            return []

        # 1.5 Dynamic Streamer Trigger
        # Ensure that viewing this coin triggers a live data subscription if not already active.
        try:
            await redis_client.publish("streamer:commands", json.dumps({
                "action": "subscribe",
                "symbol": symbol,
                "exchange": exchange_key
            }))
        except Exception as e:
            # Non-blocking failure; we don't want to fail the API call if Redis PubSub fails
            logger.warning("Failed to trigger dynamic subscription: %s", e)

        # 2. Check Cache (Keyed by Symbol + Timestamp)
        # This ensures we always serve fresh results without re-calculating if data hasn't changed
        cache_key = f"analysis:{exchange_key}:{symbol}:{int(latest_ts.timestamp())}"
        try:
            cached_result = await redis_client.get(cache_key)
        except Exception:
            cached_result = None
        
        if cached_result:
             try:
                 return json.loads(cached_result)
             except (TypeError, ValueError, json.JSONDecodeError):
                 pass

        # 3. Compute (Cache Miss)
        price_data = (
            db.query(Price)
            .filter(Price.exchange == exchange_key, Price.symbol == symbol)
            .order_by(Price.timestamp.desc())
            .limit(500)
            .all()
        )

        df = pd.DataFrame(
            [(p.timestamp, float(p.high), float(p.low), float(p.open), float(p.close), float(p.volume) if p.volume else 0.0) for p in price_data],
            columns=["timestamp", "high", "low", "open", "close", "volume"],
        )
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values(by="timestamp")
        
        for col in ("close", "high", "low", "volume"):
            df[col] = pd.to_numeric(df[col])

        # Run CPU-intensive analysis in threadpool to avoid blocking event loop
        analysis_df = await asyncio.to_thread(add_technical_indicators, df)
        
        # Ensure timestamps are serialized to strings
        if "timestamp" in analysis_df.columns:
            analysis_df["timestamp"] = analysis_df["timestamp"].astype(str)
        
        result = analysis_df.to_dict(orient="records")
        
        # Add metadata for "Signal Age" feature
        response = {
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "data": result
        }
        
        # Cache for 24h (or until timestamp changes, effectively forever for this specific candle set)
        try:
            await redis_client.setex(cache_key, 86400, json.dumps(response))
        except Exception:
            pass
        
        return response

    @api.get("/coin/{symbol:path}/quant", tags=["Analysis"])
    async def get_coin_quant_metrics(
        symbol: str,
        exchange: str | None = Query(
            default="auto",
            description="Exchange to use (auto or exchange id).",
        ),
        db: Session = Depends(get_db),
    ):
        """
        Returns institutional-grade quantitative risk metrics (Sharpe, Sortino, Volatility, etc.)
        """
        symbol = _normalize_dash_symbol(symbol)
        exchange_key = resolve_price_exchange(db, symbol, exchange)
        symbol = _normalize_symbol_for_exchange(exchange_key, symbol)
        # 1. Get Latest Timestamp
        latest_ts = db.query(func.max(Price.timestamp)).filter(Price.exchange == exchange_key, Price.symbol == symbol).scalar()
        
        if not latest_ts:
             # Trigger On-Demand Backfill
            from celery_worker.tasks import backfill_historical_candles
            if _should_enqueue_celery():
                try:
                    backfill_historical_candles.delay(symbol=symbol, exchange_id=exchange_key)
                except Exception:
                    pass

            metrics = {
                "annualized_volatility": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "sortino_ratio": 0.0,
            }
            return {
                "calculated_at": datetime.now(timezone.utc).isoformat(),
                "data": metrics,
            }
            
        # 2. Check Cache
        cache_key = f"quant:{exchange_key}:{symbol}:{int(latest_ts.timestamp())}"
        try:
            cached_result = await redis_client.get(cache_key)
        except Exception:
            cached_result = None
        
        if cached_result:
             try:
                 return json.loads(cached_result)
             except (TypeError, ValueError, json.JSONDecodeError):
                 pass
                 
        # 3. Compute (Cache Miss)
        price_data = (
            db.query(Price)
            .filter(Price.exchange == exchange_key, Price.symbol == symbol)
            .order_by(Price.timestamp.desc())
            .limit(365) # 1 year lookback for quant metrics
            .all()
        )

        df = pd.DataFrame(
            [(p.timestamp, float(p.close)) for p in price_data],
            columns=["timestamp", "close"],
        ).sort_values(by="timestamp")
        
        df["close"] = pd.to_numeric(df["close"])
        
        # Run calculation in threadpool
        metrics = await asyncio.to_thread(calculate_risk_metrics, df)
        
        # Ensure serialization (if metrics contains Timestamps)
        # Typically calculate_quant_metrics returns a dict of floats, but if it returns dates, handle them.
        # However, checking the logs, the error might also come from the response metadata if I added one.
        
        response = {
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "data": metrics
        }
        # Cache for 24h (versioned by timestamp)
        try:
            await redis_client.setex(cache_key, 86400, json.dumps(response))
        except Exception:
            pass
        
        return response

    @api.get("/coin/{query}/fundamentals", tags=["Data"])
    async def get_coin_fundamentals_endpoint(
        query: str, 
        source: str = "coingecko",
        cg: CoinGeckoConnector = Depends(get_coingecko_connector),
        cmc: CoinMarketCapConnector = Depends(get_coinmarketcap_connector)
    ):
        """
        Returns fundamental data. Accepts CoinGecko ID OR Symbol (e.g. 'BTC').
        Source can be 'coingecko' (default) or 'coinmarketcap'.
        """
        data = None
        source = source.lower()

        if source == "coinmarketcap":
            # CMC usually expects symbol
            data = await asyncio.to_thread(cmc.get_fundamentals, query)
            if data and data.get("status") in ("disabled", "error"):
                 # Fallback to coingecko if cmc fails/disabled
                 data = None
        
        if not data:
            # Try CoinGecko (as ID first)
            data = await asyncio.to_thread(cg.get_coin_fundamentals, query)
            
            if not data:
                # Try resolving from symbol
                resolved_id = await asyncio.to_thread(cg.get_coin_id_by_symbol, query)
                if resolved_id:
                    data = await asyncio.to_thread(cg.get_coin_fundamentals, resolved_id)
        
        if not data:
             raise HTTPException(status_code=404, detail=f"Fundamentals not found for '{query}'")
        return data

    @api.get("/news", tags=["Data"])
    async def get_crypto_news(
        query: str = "crypto", 
        language: str = "en", 
        sort_by: str = "relevancy",
        news_api: NewsConnector = Depends(get_news_connector),
        fmp: FinancialModelingPrepConnector = Depends(get_fmp_connector),
        newsdata: NewsDataIoConnector = Depends(get_newsdata_connector),
        paprika: CoinPaprikaConnector = Depends(get_coinpaprika_connector),
    ):
        """
        Fetches and aggregates latest crypto news from multiple sources:
        - NewsAPI (Headlines)
        - Financial Modeling Prep (Crypto News)
        - NewsData.io
        - CoinPaprika (Events)
        
        Returns a unified list of articles sorted by date.
        """
        import asyncio
        
        # Helper to normalize articles
        def normalize_article(source_name, item):
            # Default schema
            article = {
                "source": source_name,
                "title": item.get("title") or item.get("name"),
                "description": item.get("description") or item.get("text"),
                "url": item.get("url") or item.get("link"),
                "published_at": item.get("publishedAt") or item.get("published_date") or item.get("date"),
                "image_url": item.get("urlToImage") or item.get("image_url") or item.get("image"),
            }
            # FMP specific
            if source_name == "FinancialModelingPrep":
                article["title"] = item.get("title")
                article["description"] = item.get("text")
                article["url"] = item.get("url")
                article["published_at"] = item.get("publishedDate")
                article["image_url"] = item.get("image")
            
            # Coinpaprika specific
            if source_name == "CoinPaprika":
                 article["title"] = item.get("name")
                 article["description"] = item.get("description")
                 article["published_at"] = item.get("date")
                 
            return article

        # Run fetches in parallel using threads (since requests is synchronous) 
        # or just async if wrappers were async. Currently wrappers are sync `requests`.
        # We'll use asyncio.to_thread for better non-blocking behavior.

        async def fetch_news_api():
            res = await asyncio.to_thread(news_api.get_crypto_news, query, language, sort_by)
            return ("NewsAPI", res.get("articles", []) if res and "articles" in res else [])

        async def fetch_fmp():
            # FMP usually takes symbol, query might be 'bitcoin' or 'BTC'. 
            # If query is generic 'crypto', FMP endpoint /stock_news might be better, but we stick to crypto endpoint
            # FMP crypto news might expect a specific symbol list or generic. 
            res = await asyncio.to_thread(fmp.get_crypto_news, query.upper() if len(query) < 5 else "BTC")
            return ("FinancialModelingPrep", res if isinstance(res, list) else [])

        async def fetch_newsdata():
            res = await asyncio.to_thread(newsdata.get_crypto_news, query)
            return ("NewsData.io", res.get("results", []) if res and "results" in res else [])

        async def fetch_paprika():
            # Paprika expects ID (e.g. btc-bitcoin). If query is 'bitcoin', we might need to resolve ID or skip
            # For now, if query looks like a symbol, we assume main event. or just skip if no ID known.
            # We'll try to use the query as ID if it contains hyphen, else default to btc-bitcoin for demo if query is 'bitcoin'
            c_id = query.lower()
            if "bitcoin" in c_id and "-" not in c_id:
                c_id = "btc-bitcoin"
            if "ethereum" in c_id and "-" not in c_id:
                c_id = "eth-ethereum"
            
            if "-" in c_id:
                res = await asyncio.to_thread(paprika.get_news, c_id)
                return ("CoinPaprika", res.get("events", []) if res else [])
            return ("CoinPaprika", [])

        # Execute parallel
        results = await asyncio.gather(
            fetch_news_api(), 
            fetch_fmp(), 
            fetch_newsdata(), 
            fetch_paprika(), 
            return_exceptions=True
        )

        aggregated = []
        for res in results:
            if isinstance(res, Exception):
                continue
            source_name, items = res
            if items:
                 for item in items:
                     aggregated.append(normalize_article(source_name, item))

        # Sort by date (descending)
        # Handle cases where date might be None or unparseable string
        def parse_date(d):
            if not d:
                return ""
            return str(d)
        
        aggregated.sort(key=lambda x: parse_date(x["published_at"]), reverse=True)
        
        return {
            "query": query,
            "count": len(aggregated),
            "articles": aggregated
        }

    @api.get("/coin/{query}/sentiment", tags=["Data"])
    async def get_coin_sentiment_endpoint(query: str):
        """
        Returns sentiment data from multiple sources + Fear & Greed Index.
        """
        sentiment_engine = Sentiment()
        return await sentiment_engine.get_sentiment(query)

    # --- Signal Generation ---
    @api.get("/signals/batch", tags=["Analysis"])
    async def get_batch_signals(
        db: Session = Depends(get_db),
        symbols: str = Query(default="BTC-USD,ETH-USD,SOL-USD", description="Comma-separated symbols"),
        exchange: str | None = Query(
            default="auto",
            description="Exchange to use (auto or exchange id).",
        ),
    ):
        """
        Generate trading signals for multiple symbols.
        Cached for 60 seconds to prevent dashboard overload.
        """
        exchange_key = (exchange or "auto").strip().lower()

        # Check Cache
        cache_key = f"signals:batch:{exchange_key}:{symbols.replace(' ', '')}"
        cached = await redis_client.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        symbol_list = [s.strip().upper().replace("/", "-") for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            raise HTTPException(status_code=400, detail="No symbols provided")
        
        exchange_map = {
            sym: (exchange_key if exchange_key != "auto" else resolve_price_exchange(db, sym, exchange_key))
            for sym in symbol_list
        }
        exchange_map = {sym: ex for sym, ex in exchange_map.items() if ex}

        engine = SignalEngine(db)
        # Run in threadpool
        signals = await asyncio.to_thread(
            engine.generate_signals_batch,
            symbol_list,
            exchange_map=exchange_map,
            include_externals=False,
        )
        
        response = {
            "count": len(signals),
            "signals": [s.to_dict() for s in signals],
            "calculated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Cache for 60s
        await redis_client.setex(cache_key, 60, json.dumps(response))
        
        return response

    @api.get("/signals/{symbol:path}", tags=["Analysis"])
    async def get_trading_signal(
        symbol: str,
        exchange: str | None = Query(
            default="auto",
            description="Exchange to use (auto or exchange id).",
        ),
        db: Session = Depends(get_db),
        lookback: int = Query(default=500, ge=50, le=2000, description="Number of candles to analyze"),
    ):
        """
        Generate a trading signal for the given symbol.
        """
        symbol = symbol.strip().upper().replace("/", "-")
        exchange_key = resolve_price_exchange(db, symbol, exchange)
        symbol = _normalize_symbol_for_exchange(exchange_key, symbol)
        if not exchange_key:
            raise HTTPException(status_code=404, detail="No price data available for this symbol.")
        # 1. Get Latest Timestamp
        latest_ts = db.query(func.max(Price.timestamp)).filter(Price.exchange == exchange_key, Price.symbol == symbol).scalar()
        
        if not latest_ts:
             raise HTTPException(
                status_code=404,
                detail=f"Insufficient data for {symbol}. Please trigger a backfill first.",
            )

        # 2. Check Cache
        cache_key = f"signal:{exchange_key}:{symbol}:{lookback}:{int(latest_ts.timestamp())}"
        cached = await redis_client.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        # 3. Compute (Cache Miss)
        engine = SignalEngine(db)
        # Run in threadpool
        signal = await asyncio.to_thread(engine.generate_signal, symbol, lookback=lookback, exchange=exchange_key)
        
        if signal is None:
            raise HTTPException(
                status_code=404,
                detail=f"Insufficient data for {symbol}. Please trigger a backfill first.",
            )
        
        response = signal.to_dict()
        
        # Cache results (versioned by timestamp)
        await redis_client.setex(cache_key, 86400, json.dumps(response))
        
        return response

    app.include_router(api)

    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "CryptoInsight API is running. Go to /docs for documentation."}

    return app


app = create_app()













