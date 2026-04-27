from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.instrument import Coin, Price
from app.models.research import AssetDataStatus, ExchangeMarket
from app.services.asset_status import classify_asset
from app.signals.engine import SignalEngine
from celery_app import celery_app


SUPPORTED_QUOTES = {"USD", "USDT", "USDC"}


async def sync_exchange_markets(db: Session, exchange: str = "kraken") -> dict[str, Any]:
    exchange_key = (exchange or settings.PRIMARY_EXCHANGE or "kraken").strip().lower()
    exchange_cls = getattr(ccxt, exchange_key, None)
    if exchange_cls is None:
        raise ValueError(f"Unsupported CCXT exchange: {exchange_key}")

    client = exchange_cls({"enableRateLimit": True})
    now = datetime.now(timezone.utc)
    seen = 0
    stored = 0
    seen_symbols: set[str] = set()
    try:
        markets = await client.load_markets()
        for market in markets.values():
            if not _is_supported_spot(market):
                continue
            base = str(market.get("base") or "").upper()
            quote = str(market.get("quote") or "").upper()
            ccxt_symbol = str(market.get("symbol") or "")
            if not base or not quote or not ccxt_symbol:
                continue
            db_symbol = ccxt_symbol.replace("/", "-").upper()
            seen_symbols.add(db_symbol)
            classification = classify_asset(base)
            is_analyzable = bool(classification.is_analyzable)
            row = (
                db.query(ExchangeMarket)
                .filter(ExchangeMarket.exchange == exchange_key, ExchangeMarket.db_symbol == db_symbol)
                .first()
            )
            limits = market.get("limits") or {}
            amount_limits = limits.get("amount") or {}
            cost_limits = limits.get("cost") or {}
            if row is None:
                row = ExchangeMarket(exchange=exchange_key, db_symbol=db_symbol, ccxt_symbol=ccxt_symbol)
                db.add(row)
            row.ccxt_symbol = ccxt_symbol
            row.base = base
            row.quote = quote
            row.spot = bool(market.get("spot", True))
            row.active = market.get("active") is not False
            row.is_analyzable = is_analyzable
            row.min_order_amount = _float_or_none(amount_limits.get("min"))
            row.min_order_cost = _float_or_none(cost_limits.get("min"))
            row.precision_json = market.get("precision") or {}
            row.limits_json = limits
            row.metadata_json = {
                "id": market.get("id"),
                "classification_status": classification.status,
                "classification_reason": classification.reason,
            }
            row.last_seen_at = now
            seen += 1
        if seen_symbols:
            (
                db.query(ExchangeMarket)
                .filter(
                    ExchangeMarket.exchange == exchange_key,
                    ExchangeMarket.db_symbol.notin_(seen_symbols),
                )
                .update({"active": False}, synchronize_session=False)
            )
        db.flush()
        stored = (
            db.query(ExchangeMarket)
            .filter(ExchangeMarket.exchange == exchange_key, ExchangeMarket.last_seen_at == now)
            .count()
        )
    finally:
        try:
            await client.close()
            await asyncio.sleep(0)
        except Exception:
            pass
    return {"status": "ok", "exchange": exchange_key, "seen": seen, "stored": stored}


def list_market_assets(
    db: Session,
    *,
    exchange: str = "kraken",
    scope: str = "ready",
    limit: int = 500,
    offset: int = 0,
    search: str | None = None,
) -> dict[str, Any]:
    exchange_key = (exchange or settings.PRIMARY_EXCHANGE or "kraken").strip().lower()
    scope_key = (scope or "ready").strip().lower()
    limit = max(1, min(int(limit or settings.MARKET_DEFAULT_PAGE_SIZE), 5000))
    offset = max(0, int(offset or 0))

    markets = _market_rows(db, exchange_key, search)
    status_map = {
        row.symbol: row
        for row in db.query(AssetDataStatus).filter(AssetDataStatus.exchange == exchange_key).all()
    }
    if not markets:
        markets = _fallback_markets_from_status(db, exchange_key, search)

    def include_market(market: ExchangeMarket) -> bool:
        status = status_map.get(market.db_symbol)
        if scope_key == "ready":
            return bool(
                status
                and status.status in {"ready", "stale"}
                and status.is_analyzable
                and int(status.row_count or 0) >= 50
            )
        return True

    filtered = [market for market in markets if include_market(market)]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    latest_prices = _latest_prices(db, exchange_key, [market.db_symbol for market in page])
    coin_map = _coin_metadata(db, [market.base for market in page])
    signal_map = _signal_map(db, exchange_key, page, status_map) if scope_key == "ready" else {}

    items = [
        _market_payload(
            market,
            status_map.get(market.db_symbol),
            latest_prices.get(market.db_symbol),
            coin_map.get(market.base),
            signal_map.get(market.db_symbol),
        )
        for market in page
    ]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "counts": _market_counts(markets, status_map),
    }


def queue_kraken_backfills(db: Session, *, limit: int = 500, days: int = 7) -> dict[str, Any]:
    exchange_key = "kraken"
    active_count = (
        db.query(AssetDataStatus)
        .filter(
            AssetDataStatus.exchange == exchange_key,
            AssetDataStatus.status.in_(["backfill_pending", "warming_up"]),
        )
        .count()
    )
    if active_count >= settings.KRAKEN_BACKFILL_MAX_ACTIVE:
        return {
            "status": "throttled",
            "exchange": exchange_key,
            "active": active_count,
            "queued": 0,
            "reason": "Kraken backfill active task cap reached.",
        }

    batch_size = max(1, min(limit, settings.KRAKEN_BACKFILL_BATCH_SIZE))
    available_slots = max(0, settings.KRAKEN_BACKFILL_MAX_ACTIVE - active_count)
    batch_size = min(batch_size, available_slots)
    if batch_size <= 0:
        return {"status": "throttled", "exchange": exchange_key, "active": active_count, "queued": 0}

    status_map = {
        row.symbol: row
        for row in db.query(AssetDataStatus).filter(AssetDataStatus.exchange == exchange_key).all()
    }
    markets = (
        db.query(ExchangeMarket)
        .filter(
            ExchangeMarket.exchange == exchange_key,
            ExchangeMarket.active.is_(True),
            ExchangeMarket.spot.is_(True),
            ExchangeMarket.is_analyzable.is_(True),
            ExchangeMarket.quote.in_(SUPPORTED_QUOTES),
        )
        .order_by(ExchangeMarket.db_symbol.asc())
        .all()
    )
    targets = []
    for market in markets:
        status = status_map.get(market.db_symbol)
        if status and status.status == "ready" and int(status.row_count or 0) >= 200:
            continue
        if status and status.status == "backfill_pending":
            continue
        targets.append(market)
        if len(targets) >= batch_size:
            break

    queued = []
    for market in targets:
        task = celery_app.send_task(
            "celery_worker.tasks.backfill_historical_candles",
            kwargs={
                "symbol": market.db_symbol,
                "exchange_id": exchange_key,
                "days": days,
                "timeframe": "1m",
            },
        )
        status = status_map.get(market.db_symbol)
        if status is None:
            status = AssetDataStatus(
                exchange=exchange_key,
                symbol=market.db_symbol,
                base_symbol=market.base,
                status="backfill_pending",
                is_supported=True,
                is_analyzable=True,
                row_count=0,
            )
            db.add(status)
        status.status = "backfill_pending"
        status.is_supported = True
        status.is_analyzable = True
        status.last_backfill_task_id = task.id
        status.last_backfill_started_at = datetime.now(timezone.utc)
        status.last_failure_reason = None
        queued.append({"symbol": market.db_symbol, "task_id": task.id})
    db.flush()
    return {"status": "queued", "exchange": exchange_key, "queued": len(queued), "tasks_sample": queued[:10]}


def _market_rows(db: Session, exchange: str, search: str | None) -> list[ExchangeMarket]:
    query = db.query(ExchangeMarket).filter(
        ExchangeMarket.exchange == exchange,
        ExchangeMarket.active.is_(True),
        ExchangeMarket.spot.is_(True),
        ExchangeMarket.quote.in_(SUPPORTED_QUOTES),
    )
    if search:
        value = f"%{search.strip().upper()}%"
        query = query.filter((ExchangeMarket.db_symbol.ilike(value)) | (ExchangeMarket.base.ilike(value)))
    return query.order_by(ExchangeMarket.is_analyzable.desc(), ExchangeMarket.db_symbol.asc()).all()


def _fallback_markets_from_status(db: Session, exchange: str, search: str | None) -> list[ExchangeMarket]:
    query = db.query(AssetDataStatus).filter(AssetDataStatus.exchange == exchange)
    if search:
        value = f"%{search.strip().upper()}%"
        query = query.filter(AssetDataStatus.symbol.ilike(value))
    rows = query.order_by(AssetDataStatus.symbol.asc()).all()
    markets = []
    for row in rows:
        base = row.base_symbol or row.symbol.split("-", 1)[0]
        quote = row.symbol.split("-", 1)[1] if "-" in row.symbol else "USD"
        markets.append(
            ExchangeMarket(
                exchange=exchange,
                ccxt_symbol=row.symbol.replace("-", "/"),
                db_symbol=row.symbol,
                base=base,
                quote=quote,
                spot=True,
                active=True,
                is_analyzable=bool(row.is_analyzable),
            )
        )
    return markets


def _latest_prices(db: Session, exchange: str, symbols: list[str]) -> dict[str, Price]:
    if not symbols:
        return {}
    latest_rows = (
        db.query(Price.symbol, func.max(Price.timestamp).label("latest_ts"))
        .filter(Price.exchange == exchange, Price.symbol.in_(symbols))
        .group_by(Price.symbol)
        .all()
    )
    latest_by_symbol = {symbol: latest_ts for symbol, latest_ts in latest_rows if latest_ts is not None}
    if not latest_by_symbol:
        return {}
    rows = (
        db.query(Price)
        .filter(
            Price.exchange == exchange,
            Price.symbol.in_(latest_by_symbol.keys()),
            Price.timestamp.in_(latest_by_symbol.values()),
        )
        .all()
    )
    return {row.symbol: row for row in rows}


def _coin_metadata(db: Session, bases: list[str]) -> dict[str, Coin]:
    if not bases:
        return {}
    rows = db.query(Coin).filter(Coin.symbol.in_([base.lower() for base in bases] + [base.upper() for base in bases])).all()
    return {row.symbol.upper(): row for row in rows if row.symbol}


def _signal_map(
    db: Session,
    exchange: str,
    markets: list[ExchangeMarket],
    status_map: dict[str, AssetDataStatus],
) -> dict[str, dict[str, Any]]:
    ready_symbols = [
        market.db_symbol
        for market in markets
        if (status := status_map.get(market.db_symbol))
        and status.status in {"ready", "stale"}
        and int(status.row_count or 0) >= 50
    ]
    if not ready_symbols:
        return {}
    try:
        engine = SignalEngine(db)
        signals = engine.generate_signals_batch(
            ready_symbols,
            exchange_map={symbol: exchange for symbol in ready_symbols},
            lookback=60,
            include_externals=False,
        )
    except Exception:
        return {}
    return {
        signal.symbol: {
            "signal": signal.signal_type.value,
            "confidence": signal.confidence,
            "rsi": signal.indicators.get("rsi"),
            "reasons": signal.reasons,
        }
        for signal in signals
    }


def _market_payload(
    market: ExchangeMarket,
    status: AssetDataStatus | None,
    latest: Price | None,
    coin: Coin | None,
    signal: dict[str, Any] | None,
) -> dict[str, Any]:
    latest_ts = latest.timestamp if latest else status.latest_candle_at if status else None
    latest_age_seconds = None
    if latest_ts is not None:
        latest_dt = latest_ts if latest_ts.tzinfo else latest_ts.replace(tzinfo=timezone.utc)
        latest_age_seconds = int((datetime.now(timezone.utc) - latest_dt).total_seconds())
    status_value = status.status if status else "not_loaded"
    row_count = int(status.row_count or 0) if status else 0
    bot_eligible = bool(
        market.is_analyzable
        and status
        and status_value in {"ready", "stale"}
        and row_count >= 50
        and latest_age_seconds is not None
        and latest_age_seconds <= 3600
    )
    return {
        "id": f"{market.exchange}:{market.db_symbol}",
        "exchange": market.exchange,
        "symbol": market.db_symbol,
        "ccxt_symbol": market.ccxt_symbol,
        "base": market.base,
        "quote": market.quote,
        "name": coin.name if coin and coin.name else market.base,
        "image": coin.image if coin and coin.image else "",
        "current_price": float(latest.close) if latest and latest.close is not None else coin.current_price if coin else None,
        "market_cap": coin.market_cap if coin else None,
        "price_change_percentage_24h": coin.price_change_percentage_24h if coin else None,
        "analysis": signal or {},
        "data_status": {
            "status": status_value,
            "reason": status.last_failure_reason if status else "Market discovered; no candle backfill has completed yet.",
            "exchange": market.exchange,
            "symbol": market.db_symbol,
            "row_count": row_count,
            "latest_candle_at": latest_ts.isoformat() if latest_ts else None,
            "latest_age_seconds": latest_age_seconds,
        },
        "bot_eligible": bot_eligible,
        "is_analyzable": bool(market.is_analyzable),
        "last_seen_at": market.last_seen_at.isoformat() if market.last_seen_at else None,
    }


def _market_counts(markets: list[ExchangeMarket], status_map: dict[str, AssetDataStatus]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    ready = 0
    analyzable = 0
    for market in markets:
        if market.is_analyzable:
            analyzable += 1
        status = status_map.get(market.db_symbol)
        key = status.status if status else "not_loaded"
        status_counts[key] = status_counts.get(key, 0) + 1
        if status and status.status in {"ready", "stale"} and int(status.row_count or 0) >= 50:
            ready += 1
    return {
        "total": len(markets),
        "analyzable": analyzable,
        "ready": ready,
        "statuses": status_counts,
    }


def _is_supported_spot(market: dict[str, Any]) -> bool:
    quote = str(market.get("quote") or "").upper()
    return (
        bool(market.get("spot", True))
        and market.get("active") is not False
        and quote in SUPPORTED_QUOTES
    )


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
