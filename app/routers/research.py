from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.instrument import Price
from app.models.research import AssetDataStatus, ExchangeMarket
from app.redis_client import redis_client
from app.services.asset_status import build_signal_status
from app.services.exchange_markets import list_market_assets, queue_kraken_backfills, sync_exchange_markets
from app.services.market_resolution import normalize_db_symbol
from app.services.price_selection import resolve_price_exchange
from app.signals.engine import SignalEngine
from database import get_db


router = APIRouter(prefix="/research", tags=["Research"])
ops_router = APIRouter(prefix="/operations", tags=["Operations"])
market_router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/assets/{exchange}/{symbol:path}")
async def get_asset_research_snapshot(
    exchange: str,
    symbol: str,
    lookback: int = Query(default=200, ge=50, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    exchange_key = (exchange or "auto").strip().lower()
    raw_symbol = symbol.strip().upper().replace("/", "-")
    if exchange_key == "auto":
        normalized_for_priority = raw_symbol if "-" in raw_symbol else f"{raw_symbol}-USD"
        resolved_exchange = resolve_price_exchange(db, normalized_for_priority, exchange_key)
        exchange_key = resolved_exchange or "coinbase"

    db_symbol = normalize_db_symbol(raw_symbol, exchange_key)

    latest_ts = (
        db.query(func.max(Price.timestamp))
        .filter(Price.exchange == exchange_key, Price.symbol == db_symbol)
        .scalar()
    )
    row_count = (
        db.query(func.count(Price.id))
        .filter(Price.exchange == exchange_key, Price.symbol == db_symbol)
        .scalar()
        or 0
    )
    latest_price = None
    if latest_ts is not None:
        latest_row = (
            db.query(Price)
            .filter(Price.exchange == exchange_key, Price.symbol == db_symbol, Price.timestamp == latest_ts)
            .first()
        )
        if latest_row and latest_row.close is not None:
            latest_price = float(latest_row.close)

    status_record = (
        db.query(AssetDataStatus)
        .filter(AssetDataStatus.exchange == exchange_key, AssetDataStatus.symbol == db_symbol)
        .first()
    )

    signal_payload = None
    signal_error = None
    if row_count >= 50:
        try:
            engine = SignalEngine(db)
            signal = await asyncio.to_thread(
                engine.generate_signal,
                db_symbol,
                lookback=lookback,
                exchange=exchange_key,
                include_externals=False,
            )
            signal_payload = signal.to_dict() if signal else None
        except Exception as exc:
            signal_error = str(exc)

    signal_status = build_signal_status(
        exchange=exchange_key,
        symbol=db_symbol,
        row_count=int(row_count),
        latest_candle_at=latest_ts,
        status_record=status_record,
        has_signal=signal_payload is not None,
    )
    if signal_status["status"] not in {"ready", "stale"}:
        signal_payload = None

    freshness_seconds = None
    if latest_ts is not None:
        latest = latest_ts if latest_ts.tzinfo else latest_ts.replace(tzinfo=timezone.utc)
        freshness_seconds = int((datetime.now(timezone.utc) - latest).total_seconds())

    return {
        "exchange": exchange_key,
        "symbol": db_symbol,
        "price": latest_price,
        "price_timestamp": latest_ts.isoformat() if latest_ts else None,
        "freshness_seconds": freshness_seconds,
        "row_count": int(row_count),
        "data_status": signal_status,
        "signal": signal_payload,
        "signal_error": signal_error,
        "known_limitations": _known_limitations(signal_status),
    }


@ops_router.get("/market")
async def get_market_operations_status(db: Session = Depends(get_db)) -> dict:
    try:
        queue_depth = int(await redis_client.llen("celery"))
    except Exception:
        queue_depth = None

    status_counts = {
        status: int(count)
        for status, count in db.query(AssetDataStatus.status, func.count(AssetDataStatus.id))
        .group_by(AssetDataStatus.status)
        .all()
    }
    latest_candle_at = db.query(func.max(Price.timestamp)).scalar()
    latest_success = (
        db.query(AssetDataStatus)
        .filter(AssetDataStatus.last_backfill_completed_at.isnot(None))
        .order_by(AssetDataStatus.last_backfill_completed_at.desc())
        .first()
    )
    recent_failures = (
        db.query(AssetDataStatus)
        .filter(AssetDataStatus.status.in_(["unsupported", "backfill_failed"]))
        .order_by(AssetDataStatus.last_backfill_failed_at.desc())
        .limit(10)
        .all()
    )

    exchange_counts = {
        exchange: int(count)
        for exchange, count in db.query(AssetDataStatus.exchange, func.count(AssetDataStatus.id))
        .group_by(AssetDataStatus.exchange)
        .all()
    }
    ready_by_exchange = {
        exchange: int(count)
        for exchange, count in db.query(AssetDataStatus.exchange, func.count(AssetDataStatus.id))
        .filter(AssetDataStatus.status == "ready", AssetDataStatus.row_count >= 50)
        .group_by(AssetDataStatus.exchange)
        .all()
    }
    discovered_by_exchange = {
        exchange: int(count)
        for exchange, count in db.query(ExchangeMarket.exchange, func.count(ExchangeMarket.id))
        .filter(ExchangeMarket.active.is_(True))
        .group_by(ExchangeMarket.exchange)
        .all()
    }
    analyzable_by_exchange = {
        exchange: int(count)
        for exchange, count in db.query(ExchangeMarket.exchange, func.count(ExchangeMarket.id))
        .filter(ExchangeMarket.active.is_(True), ExchangeMarket.is_analyzable.is_(True))
        .group_by(ExchangeMarket.exchange)
        .all()
    }
    active_backfills = {
        exchange: int(count)
        for exchange, count in db.query(AssetDataStatus.exchange, func.count(AssetDataStatus.id))
        .filter(AssetDataStatus.status.in_(["backfill_pending", "warming_up"]))
        .group_by(AssetDataStatus.exchange)
        .all()
    }

    return {
        "celery_queue_depth": queue_depth,
        "status_counts": status_counts,
        "exchange_counts": exchange_counts,
        "ready_by_exchange": ready_by_exchange,
        "discovered_by_exchange": discovered_by_exchange,
        "analyzable_by_exchange": analyzable_by_exchange,
        "active_backfills_by_exchange": active_backfills,
        "latest_candle_at": latest_candle_at.isoformat() if latest_candle_at else None,
        "latest_success": _status_summary(latest_success),
        "recent_failures": [_status_summary(row) for row in recent_failures],
    }


@market_router.get("/assets")
def get_market_assets(
    exchange: str = Query(default="kraken"),
    scope: str = Query(default="ready", pattern="^(ready|all)$"),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return list_market_assets(
        db,
        exchange=exchange,
        scope=scope,
        limit=limit,
        offset=offset,
        search=search,
    )


@ops_router.post("/market/sync-kraken")
async def sync_kraken_markets(db: Session = Depends(get_db)) -> dict:
    result = await sync_exchange_markets(db, exchange="kraken")
    db.commit()
    return result


@ops_router.post("/market/backfill-kraken")
def backfill_kraken_markets(
    limit: int = Query(default=500, ge=1, le=5000),
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
) -> dict:
    result = queue_kraken_backfills(db, limit=limit, days=days)
    db.commit()
    return result


def _status_summary(row: AssetDataStatus | None) -> dict | None:
    if row is None:
        return None
    return {
        "exchange": row.exchange,
        "symbol": row.symbol,
        "status": row.status,
        "row_count": row.row_count,
        "latest_candle_at": row.latest_candle_at.isoformat() if row.latest_candle_at else None,
        "last_failure_reason": row.last_failure_reason,
    }


def _known_limitations(data_status: dict) -> list[str]:
    limitations = []
    if data_status["status"] != "ready":
        limitations.append(data_status["reason"] or f"Data status is {data_status['status']}.")
    if data_status.get("row_count", 0) < 200:
        limitations.append("Some indicators and backtests are less reliable with fewer than 200 candles.")
    return limitations
