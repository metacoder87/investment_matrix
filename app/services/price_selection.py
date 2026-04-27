from __future__ import annotations


from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.instrument import Price
from app.services.market_resolution import configured_exchange_priority


def _normalize_exchange(value: str) -> str:
    return value.strip().lower()


def _priority_exchanges() -> list[str]:
    return [_normalize_exchange(part) for part in configured_exchange_priority()]


def resolve_price_exchange(
    db: Session,
    symbol: str,
    exchange: str | None = None,
) -> str | None:
    """
    Pick the best exchange for price data.

    - If exchange is provided and not "auto", use it.
    - Otherwise, choose the exchange with the freshest data, breaking ties by priority.
    - If no data exists, fall back to the first configured priority exchange.
    """
    if exchange:
        normalized = exchange.strip().lower()
        if normalized and normalized != "auto":
            return normalized

    priority = _priority_exchanges()
    rows = (
        db.query(Price.exchange, func.max(Price.timestamp).label("latest"))
        .filter(Price.symbol == symbol)
        .group_by(Price.exchange)
        .all()
    )

    if not rows:
        return priority[0] if priority else None

    priority_rank = {ex: idx for idx, ex in enumerate(priority)}
    best_exchange = None
    best_latest = None

    for row in rows:
        exchange_key = _normalize_exchange(row.exchange or "")
        latest = row.latest
        if latest is None:
            continue
        if best_latest is None or latest > best_latest:
            best_latest = latest
            best_exchange = exchange_key
            continue
        if latest == best_latest:
            if priority_rank.get(exchange_key, 9999) < priority_rank.get(best_exchange, 9999):
                best_exchange = exchange_key

    if best_exchange:
        return best_exchange

    available = {_normalize_exchange(row.exchange or "") for row in rows if row.exchange}
    for exchange_key in priority:
        if exchange_key in available:
            return exchange_key

    return next(iter(available), None)

