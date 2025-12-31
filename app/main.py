from __future__ import annotations

from contextlib import asynccontextmanager
import json
from datetime import datetime, timedelta, timezone
import asyncio

import pandas as pd
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analysis import add_technical_indicators
from app.analysis_quant import calculate_risk_metrics
from app.config import settings
from app.connectors.fundamental import CoinGeckoConnector
from app.connectors.sentiment import Sentiment
from app.connectors.news_api import NewsConnector
from app.connectors.coinmarketcap import CoinMarketCapConnector
from app.connectors.coinpaprika import CoinPaprikaConnector
from app.connectors.financialmodelingprep import FinancialModelingPrepConnector
from app.connectors.newsdata_io import NewsDataIoConnector
from app.redis_client import redis_client
from app.models.market import MarketTrade
from app.models.instrument import Price
from celery_app import celery_app
from app.signals.engine import SignalEngine
from database import get_db, init_db


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
        init_db()
        yield

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=f"{settings.API_PREFIX}/docs",
        redoc_url=f"{settings.API_PREFIX}/redoc",
        openapi_url=f"{settings.API_PREFIX}/openapi.json",
    )

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix=settings.API_PREFIX)

    @api.get("/health", tags=["Meta"])
    async def health():
        return {"status": "ok"}

    # --- Ingestion Endpoints (Celery-triggered) ---
    @api.post("/ingest/prices/{symbol:path}", status_code=202, tags=["Ingestion"])
    async def start_price_ingestion(
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        exchange: str = "binance",
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
        exchange: str = Query(default="coinbase", description="Exchange to fetch from"),
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
        exchange: str = Query(default="coinbase"),
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
    async def get_coins_list(cg: CoinGeckoConnector = Depends(get_coingecko_connector)):
        return cg.get_all_coins(per_page=100, page=1)

    @api.get("/market/latest/{symbol:path}", tags=["Data"])
    async def get_latest_tick(symbol: str):
        raw = await redis_client.get(f"latest:{symbol}")
        if not raw:
            raise HTTPException(status_code=404, detail="No live data yet for this symbol.")
        return json.loads(raw)

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

    def _normalize_symbol_for_exchange(exchange: str, symbol: str) -> str:
        exchange = exchange.strip().lower()
        symbol = _normalize_dash_symbol(symbol)
        if exchange == "binance" and symbol.endswith("-USD"):
            return f"{symbol[:-4]}-USDT"
        return symbol

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
        symbol = _normalize_symbol_for_exchange(exchange, symbol)

        end_dt = _to_utc(end) if end else datetime.now(timezone.utc)
        start_dt = _to_utc(start) if start else end_dt - timedelta(hours=1)
        if start_dt > end_dt:
            raise HTTPException(status_code=400, detail="Invalid time range: start must be <= end.")

        range_seconds = max(1.0, (end_dt - start_dt).total_seconds())
        bucket_seconds = _choose_bucket_seconds(range_seconds, max_points)

        dialect = db.get_bind().dialect.name
        points: list[dict] = []
        if dialect == "postgresql":
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
        Returns OHLCV candles derived from persisted tick trades in `market_trades`.

        - Uses TimescaleDB `time_bucket` + `first/last` on Postgres.
        - Falls back to Python aggregation for SQLite/tests.
        """
        exchange = exchange.strip().lower()
        symbol = _normalize_symbol_for_exchange(exchange, symbol)

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
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
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
            except Exception:
                candles = []

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

        # Fallback: query the prices table (used by backfill) if no data in market_trades
        if not candles:
            prices_rows = (
                db.query(Price)
                .filter(
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

        return {
            "exchange": exchange,
            "symbol": symbol,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "timeframe": timeframe,
            "requested_bucket_seconds": requested_bucket_seconds,
            "bucket_seconds": bucket_seconds,
            "candles": candles,
        }

    @api.get("/market/coverage/{exchange}/{symbol:path}", tags=["Data"])
    async def get_market_coverage(exchange: str, symbol: str, db: Session = Depends(get_db)):
        """
        Returns what is currently persisted in TimescaleDB for a given exchange+symbol.

        Useful for validating that the writer is storing trades and for estimating how much historic data you have.
        """
        exchange = exchange.strip().lower()
        symbol = _normalize_symbol_for_exchange(exchange, symbol)

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
        }

    @api.get("/coin/{symbol:path}/analysis", tags=["Analysis"])
    async def get_coin_analysis(symbol: str, db: Session = Depends(get_db)):
        price_data = (
            db.query(Price)
            .filter(Price.symbol == symbol)
            .order_by(Price.timestamp.desc())
            .limit(500)
            .all()
        )
        if not price_data:
            raise HTTPException(
                status_code=404,
                detail="No price data found for this symbol. Please ingest data first.",
            )

        df = pd.DataFrame(
            [(p.timestamp, p.high, p.low, p.open, p.close, p.volume) for p in price_data],
            columns=["timestamp", "high", "low", "open", "close", "volume"],
        ).sort_values(by="timestamp")
        for col in ("close", "high", "low", "volume"):
            df[col] = pd.to_numeric(df[col])

        analysis_df = add_technical_indicators(df)
        return analysis_df.to_dict(orient="records")

    @api.get("/coin/{symbol:path}/quant", tags=["Analysis"])
    async def get_coin_quant_metrics(symbol: str, db: Session = Depends(get_db)):
        """
        Returns institutional-grade quantitative risk metrics (Sharpe, Sortino, Volatility, etc.)
        """
        price_data = (
            db.query(Price)
            .filter(Price.symbol == symbol)
            .order_by(Price.timestamp.desc())
            .limit(365) # Analyze last 1 year max
            .all()
        )
        if not price_data:
            raise HTTPException(status_code=404, detail="No price data found.")
            
        df = pd.DataFrame(
            [(p.timestamp, float(p.close)) for p in reversed(price_data)],
            columns=["timestamp", "close"]
        ).set_index("timestamp")
        
        return calculate_risk_metrics(df)

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
        return sentiment_engine.get_sentiment(query)

    # --- Signal Generation ---
    @api.get("/signals/{symbol:path}", tags=["Analysis"])
    async def get_trading_signal(
        symbol: str,
        db: Session = Depends(get_db),
        lookback: int = Query(default=500, ge=50, le=2000, description="Number of candles to analyze"),
    ):
        """
        Generate a trading signal for the given symbol.
        
        Combines RSI, MACD, Bollinger Bands, SMA crossovers, and volume analysis
        to produce a buy/sell/hold recommendation with confidence score.
        """

        
        symbol = symbol.strip().upper().replace("/", "-")
        engine = SignalEngine(db)
        signal = engine.generate_signal(symbol, lookback=lookback)
        
        if signal is None:
            raise HTTPException(
                status_code=404,
                detail=f"Insufficient data for {symbol}. Please trigger a backfill first.",
            )
        
        return signal.to_dict()

    @api.get("/signals/batch", tags=["Analysis"])
    async def get_batch_signals(
        db: Session = Depends(get_db),
        symbols: str = Query(default="BTC-USD,ETH-USD,SOL-USD", description="Comma-separated symbols"),
    ):
        """
        Generate trading signals for multiple symbols.
        """

        
        symbol_list = [s.strip().upper().replace("/", "-") for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            raise HTTPException(status_code=400, detail="No symbols provided")
        
        engine = SignalEngine(db)
        signals = engine.generate_signals_batch(symbol_list)
        
        return {
            "count": len(signals),
            "signals": [s.to_dict() for s in signals],
        }

    app.include_router(api)

    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "CryptoInsight API is running. Go to /api/docs for documentation."}

    return app


app = create_app()
