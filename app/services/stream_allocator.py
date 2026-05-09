from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.instrument import Coin
from app.models.research import (
    AgentRecommendation,
    AssetDataStatus,
    DataSourceHealth,
    ExchangeMarket,
    MarketQuote,
    StreamTarget,
    AgentResearchThesis,
)
from app.models.paper import PaperPosition
from app.redis_client import RedisClient
from app.services.data_sources import configured_stream_sources, ensure_source_catalog, source_unavailable_reason
from app.services.ingestion_telemetry import latest_capacity_snapshot


@dataclass(frozen=True)
class AllocationResult:
    status: str
    evaluated: int
    active: int
    replacements: dict[str, list[str]]


def allocate_stream_targets(db: Session, *, publish_commands: bool = False) -> dict[str, Any]:
    ensure_source_catalog(db)
    now = datetime.now(timezone.utc)
    locked = _symbol_set(settings.STREAM_USER_LOCKED_SYMBOLS)
    
    active_positions = db.query(PaperPosition).filter(PaperPosition.quantity > 0).all()
    for pos in active_positions:
        locked.add(pos.symbol.upper())
        
    active_theses = db.query(AgentResearchThesis).filter(AgentResearchThesis.status.in_(["open", "triggered"])).all()
    for thesis in active_theses:
        locked.add(thesis.symbol.upper())

    blocked = _symbol_set(settings.STREAM_USER_BLOCKED_SYMBOLS)
    source_order = configured_stream_sources()
    max_per_exchange = max(1, int(settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE or 25))

    health_map = {row.source: row for row in db.query(DataSourceHealth).all()}
    existing_targets = {
        (row.exchange, row.symbol): row
        for row in db.query(StreamTarget).all()
    }
    capacity = latest_capacity_snapshot(db)

    market_rows = (
        db.query(ExchangeMarket)
        .filter(
            ExchangeMarket.exchange.in_(source_order),
            ExchangeMarket.active.is_(True),
            ExchangeMarket.spot.is_(True),
            ExchangeMarket.is_analyzable.is_(True),
        )
        .all()
    )
    status_map = {
        (row.exchange, row.symbol): row
        for row in db.query(AssetDataStatus).filter(AssetDataStatus.exchange.in_(source_order)).all()
    }
    quote_map = _latest_quotes(db, source_order)
    coin_map = _coin_map(db, [market.base for market in market_rows])
    edge_map = _recommendation_edge_map(db)

    scored: list[tuple[float, ExchangeMarket, dict[str, Any], str]] = []
    for market in market_rows:
        symbol = market.db_symbol.upper()
        health = health_map.get(market.exchange)
        availability_reason = source_unavailable_reason(health)
        row_pref = existing_targets.get((market.exchange, symbol))
        preference = (row_pref.user_preference if row_pref else "neutral") or "neutral"
        if symbol in locked:
            preference = "locked"
        if symbol in blocked:
            preference = "blocked"

        if preference == "blocked":
            details = {"blocked": 1.0, "reason": "User blocked symbol."}
            scored.append((0.0, market, details, preference))
            continue

        details = _score_market(
            market=market,
            health=health,
            status=status_map.get((market.exchange, symbol)),
            quote=quote_map.get((market.exchange, symbol)),
            coin=coin_map.get(market.base.upper()),
            edge=edge_map.get((market.exchange, symbol)),
            preference=preference,
            availability_reason=availability_reason,
            now=now,
        )
        score = float(details["score"])
        scored.append((score, market, details, preference))

    replacements: dict[str, list[str]] = {}
    active_keys: set[tuple[str, str]] = set()
    ranked_by_exchange: dict[str, list[tuple[float, ExchangeMarket, dict[str, Any], str]]] = {}
    for item in scored:
        ranked_by_exchange.setdefault(item[1].exchange, []).append(item)

    evaluated = 0
    for exchange in source_order:
        items = ranked_by_exchange.get(exchange, [])
        items.sort(key=lambda item: (_preference_rank(item[3]), item[0]), reverse=True)
        selected = []
        exchange_cap = _dynamic_symbol_cap(
            exchange=exchange,
            health=health_map.get(exchange),
            existing_targets=existing_targets,
            base_cap=max_per_exchange,
            capacity=capacity,
        )
        estimated_mps = _estimated_messages_per_symbol(health_map.get(exchange), existing_targets, exchange)
        for rank, (score, market, details, preference) in enumerate(items, start=1):
            symbol = market.db_symbol.upper()
            evaluated += 1
            is_selected = preference != "blocked" and len(selected) < exchange_cap
            coverage_tier = _coverage_tier(
                market=market,
                health=health_map.get(exchange),
                availability_reason=details.get("availability_reason"),
                preference=preference,
                rank=rank,
                selected=is_selected,
                base_cap=max_per_exchange,
                capacity=capacity,
            )
            is_tick_stream = coverage_tier == "tick_stream"
            if is_tick_stream:
                selected.append(symbol)
                active_keys.add((market.exchange, symbol))

            target = existing_targets.get((market.exchange, symbol))
            if target is None:
                target = StreamTarget(
                    exchange=market.exchange,
                    symbol=symbol,
                    base=market.base,
                    quote=market.quote,
                    source_type="cex",
                )
                db.add(target)
            target.base = market.base
            target.quote = market.quote
            target.source_type = "cex"
            target.rank = rank
            target.score = score
            target.active = is_tick_stream
            target.status = "active" if is_tick_stream else "blocked" if preference == "blocked" else "candidate"
            target.coverage_tier = coverage_tier
            target.capacity_state = capacity["state"]
            target.expected_messages_per_second = estimated_mps if is_tick_stream else 0.0
            target.user_preference = preference
            target.reason = details.get("reason")
            target.score_details_json = {
                **details,
                "coverage_tier": coverage_tier,
                "capacity": capacity,
                "exchange_symbol_cap": exchange_cap,
                "estimated_messages_per_symbol": round(estimated_mps, 4),
            }
            target.last_selected_at = now if is_tick_stream else target.last_selected_at
            target.last_evaluated_at = now
        if items:
            replacements[exchange] = selected

    for target in existing_targets.values():
        if (target.exchange, target.symbol) not in active_keys and target.last_evaluated_at != now:
            target.active = False
            if not target.coverage_tier:
                target.coverage_tier = "ohlcv_only"

    db.flush()
    if publish_commands and replacements:
        asyncio.run(_publish_replacements(replacements))

    return {
        "status": "ok",
        "evaluated": evaluated,
        "active": sum(len(symbols) for symbols in replacements.values()),
        "replacements": replacements,
    }


def list_stream_targets(
    db: Session,
    *,
    status: str | None = None,
    coverage_tier: str | None = None,
    exchange: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    query = db.query(StreamTarget)
    if status:
        query = query.filter(StreamTarget.status == status)
    if exchange:
        query = query.filter(StreamTarget.exchange == exchange.strip().lower())
    if coverage_tier:
        query = query.filter(StreamTarget.coverage_tier == coverage_tier.strip().lower())
    rows = (
        query.order_by(StreamTarget.active.desc(), StreamTarget.exchange.asc(), StreamTarget.rank.asc(), StreamTarget.score.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    return {"items": [_target_payload(row) for row in rows], "count": len(rows)}


def set_stream_preferences(
    db: Session,
    *,
    symbols: list[str],
    preference: str,
    exchange: str | None = None,
) -> dict[str, Any]:
    preference = preference.strip().lower()
    if preference not in {"neutral", "locked", "boosted", "blocked"}:
        raise ValueError("preference must be neutral, locked, boosted, or blocked")
    normalized_symbols = sorted(_symbol_set(",".join(symbols)))
    if not normalized_symbols:
        raise ValueError("At least one symbol is required.")

    exchange_key = exchange.strip().lower() if exchange else None
    updated = 0
    for symbol in normalized_symbols:
        targets = []
        if exchange_key:
            target = _get_or_create_preference_target(db, exchange_key, symbol)
            targets.append(target)
        else:
            targets = db.query(StreamTarget).filter(StreamTarget.symbol == symbol).all()
            if not targets:
                targets = [_get_or_create_preference_target(db, "auto", symbol)]
        for target in targets:
            target.user_preference = preference
            target.last_evaluated_at = datetime.now(timezone.utc)
            updated += 1
    db.flush()
    return {"status": "ok", "updated": updated, "symbols": normalized_symbols, "preference": preference}


def _score_market(
    *,
    market: ExchangeMarket,
    health: DataSourceHealth | None,
    status: AssetDataStatus | None,
    quote: MarketQuote | None,
    coin: Coin | None,
    edge: float | None,
    preference: str,
    availability_reason: str | None,
    now: datetime,
) -> dict[str, Any]:
    paper_edge = _clamp(edge if edge is not None else 0.0)
    liquidity = _liquidity_score(coin)
    volatility = _volatility_score(coin)
    spread_quality = _spread_score(quote)
    freshness = _freshness_score(status, now)
    interest = 1.0 if preference == "locked" else 0.7 if preference == "boosted" else 0.2
    reliability = _source_reliability_score(health, now)

    score = (
        paper_edge * 0.30
        + liquidity * 0.20
        + volatility * 0.15
        + spread_quality * 0.10
        + freshness * 0.10
        + interest * 0.10
        + reliability * 0.05
    )
    if preference == "locked":
        score += 1.0
    elif preference == "boosted":
        score += 0.25
    if availability_reason:
        score = min(score, 0.05)

    return {
        "score": round(float(score), 6),
        "paper_model_edge": round(paper_edge, 4),
        "liquidity": round(liquidity, 4),
        "volatility": round(volatility, 4),
        "spread_quality": round(spread_quality, 4),
        "freshness_need": round(freshness, 4),
        "portfolio_watchlist_interest": round(interest, 4),
        "source_reliability": round(reliability, 4),
        "availability_reason": availability_reason,
        "preference": preference,
        "reason": _reason(preference, score, status, quote, availability_reason),
    }


def _latest_quotes(db: Session, exchanges: list[str]) -> dict[tuple[str, str], MarketQuote]:
    latest = (
        db.query(MarketQuote.exchange, MarketQuote.symbol, func.max(MarketQuote.timestamp).label("latest_ts"))
        .filter(MarketQuote.exchange.in_(exchanges))
        .group_by(MarketQuote.exchange, MarketQuote.symbol)
        .all()
    )
    if not latest:
        return {}
    rows = (
        db.query(MarketQuote)
        .filter(
            MarketQuote.exchange.in_([row.exchange for row in latest]),
            MarketQuote.symbol.in_([row.symbol for row in latest]),
            MarketQuote.timestamp.in_([row.latest_ts for row in latest]),
        )
        .all()
    )
    return {(row.exchange, row.symbol): row for row in rows}


def _coin_map(db: Session, bases: list[str]) -> dict[str, Coin]:
    if not bases:
        return {}
    variants = set()
    for base in bases:
        variants.add(base.upper())
        variants.add(base.lower())
    rows = db.query(Coin).filter(Coin.symbol.in_(variants)).all()
    return {str(row.symbol).upper(): row for row in rows}


def _recommendation_edge_map(db: Session) -> dict[tuple[str, str], float]:
    rows = (
        db.query(AgentRecommendation.exchange, AgentRecommendation.symbol, func.max(AgentRecommendation.confidence).label("confidence"))
        .filter(AgentRecommendation.status.in_(["proposed", "approved", "executed"]))
        .group_by(AgentRecommendation.exchange, AgentRecommendation.symbol)
        .all()
    )
    return {(row.exchange, row.symbol): float(row.confidence or 0.0) for row in rows}


async def _publish_replacements(replacements: dict[str, list[str]]) -> None:
    redis = RedisClient.get_redis()
    for exchange, symbols in replacements.items():
        await redis.publish(
            "streamer:commands",
            json.dumps({"action": "replace_set", "exchange": exchange.upper(), "symbols": symbols}),
        )


def _get_or_create_preference_target(db: Session, exchange: str, symbol: str) -> StreamTarget:
    target = db.query(StreamTarget).filter(StreamTarget.exchange == exchange, StreamTarget.symbol == symbol).first()
    if target:
        return target
    base, quote = _split_dash(symbol)
    target = StreamTarget(
        exchange=exchange,
        symbol=symbol,
        base=base,
        quote=quote,
        source_type="cex",
        status="candidate",
        score=0.0,
        active=False,
    )
    db.add(target)
    return target


def _split_dash(symbol: str) -> tuple[str, str]:
    if "-" in symbol:
        base, quote = symbol.split("-", 1)
        return base, quote
    return symbol, "USD"


def _symbol_set(raw: str) -> set[str]:
    result: set[str] = set()
    for part in raw.split(","):
        symbol = part.strip().upper().replace("/", "-")
        if symbol:
            result.add(symbol)
    return result


def _preference_rank(preference: str) -> int:
    if preference == "locked":
        return 3
    if preference == "boosted":
        return 2
    if preference == "neutral":
        return 1
    return 0


def _liquidity_score(coin: Coin | None) -> float:
    if not coin or coin.market_cap is None:
        return 0.3
    market_cap = _float(coin.market_cap)
    if market_cap <= 0:
        return 0.3
    return _clamp((math.log10(market_cap) - 6) / 6)


def _volatility_score(coin: Coin | None) -> float:
    change = abs(float(coin.price_change_percentage_24h or 0.0)) if coin else 0.0
    return _clamp(change / 20.0)


def _spread_score(quote: MarketQuote | None) -> float:
    if not quote or quote.spread_bps is None:
        return 0.5
    return _clamp(1.0 - min(float(quote.spread_bps), 100.0) / 100.0)


def _freshness_score(status: AssetDataStatus | None, now: datetime) -> float:
    if status is None or status.latest_candle_at is None:
        return 0.8
    latest = status.latest_candle_at
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    age = now - latest
    if status.status in {"unsupported", "not_applicable"}:
        return 0.0
    if age > timedelta(hours=1):
        return 1.0
    if age > timedelta(minutes=15):
        return 0.7
    return 0.2


def _source_reliability_score(health: DataSourceHealth | None, now: datetime) -> float:
    if health is None:
        return 0.5
    if source_unavailable_reason(health):
        return 0.0
    if health.enabled is False:
        return 0.0
    if health.last_error_at:
        last_error = health.last_error_at
        if last_error.tzinfo is None:
            last_error = last_error.replace(tzinfo=timezone.utc)
        if now - last_error < timedelta(minutes=10):
            return 0.25
    if health.last_success_at:
        return 1.0
    return 0.7


def _reason(
    preference: str,
    score: float,
    status: AssetDataStatus | None,
    quote: MarketQuote | None,
    availability_reason: str | None,
) -> str:
    if availability_reason:
        return availability_reason
    if preference == "locked":
        return "User locked symbol; capacity permitting, stream first."
    if preference == "boosted":
        return "User boosted symbol; score was increased."
    parts = [f"Hybrid score {score:.3f}."]
    if status and status.status:
        parts.append(f"Data status is {status.status}.")
    if quote and quote.spread_bps is not None:
        parts.append(f"Latest spread {quote.spread_bps:.2f} bps.")
    return " ".join(parts)


def _target_payload(row: StreamTarget) -> dict[str, Any]:
    return {
        "exchange": row.exchange,
        "symbol": row.symbol,
        "base": row.base,
        "quote": row.quote,
        "source_type": row.source_type,
        "status": row.status,
        "coverage_tier": row.coverage_tier,
        "capacity_state": row.capacity_state,
        "expected_messages_per_second": row.expected_messages_per_second,
        "rank": row.rank,
        "score": row.score,
        "active": bool(row.active),
        "user_preference": row.user_preference,
        "reason": row.reason,
        "score_details": row.score_details_json or {},
        "last_selected_at": row.last_selected_at.isoformat() if row.last_selected_at else None,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
    }


def _float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _dynamic_symbol_cap(
    *,
    exchange: str,
    health: DataSourceHealth | None,
    existing_targets: dict[tuple[str, str], StreamTarget],
    base_cap: int,
    capacity: dict[str, Any],
) -> int:
    cap = max(1, int(base_cap))
    estimated = _estimated_messages_per_symbol(health, existing_targets, exchange)
    if estimated > 0:
        cap = min(cap, max(1, int(float(settings.STREAM_MAX_MESSAGES_PER_SECOND_PER_SOURCE) // estimated)))
    if capacity["state"] == "constrained":
        cap = max(1, min(cap, int(math.ceil(base_cap * 0.40))))
    return cap


def _estimated_messages_per_symbol(
    health: DataSourceHealth | None,
    existing_targets: dict[tuple[str, str], StreamTarget],
    exchange: str,
) -> float:
    active_count = sum(
        1
        for (target_exchange, _), target in existing_targets.items()
        if target_exchange == exchange and target.active
    )
    if not health or not health.messages_per_second:
        return 1.0
    return max(0.1, float(health.messages_per_second) / max(1, active_count))


def _coverage_tier(
    *,
    market: ExchangeMarket,
    health: DataSourceHealth | None,
    availability_reason: str | None,
    preference: str,
    rank: int,
    selected: bool,
    base_cap: int,
    capacity: dict[str, Any],
) -> str:
    if preference == "blocked":
        return "blocked"
    if availability_reason:
        return "ohlcv_only"
    websocket_ok = bool(health and health.enabled is not False and health.websocket_supported)
    if selected and websocket_ok:
        return "tick_stream"
    if health and health.quote_supported and (preference in {"locked", "boosted"} or rank <= max(1, base_cap * 2)):
        return "quote_stream"
    if health and health.recent_trades_supported and rank <= max(1, base_cap * 4):
        return "rest_gap_fill"
    if getattr(market, "source_type", "cex") == "dex":
        return "dex_context_only"
    return "ohlcv_only"
