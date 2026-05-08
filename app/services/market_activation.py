from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.research import AssetDataStatus, DataSourceHealth, ExchangeMarket, StreamTarget
from app.services.data_sources import configured_stream_sources, ensure_source_catalog, source_unavailable_reason
from app.services.stream_allocator import allocate_stream_targets
from celery_app import celery_app


READY_CANDLE_COUNT = 50


def activate_market_coverage(
    db: Session,
    *,
    queue_work: bool = True,
    limit: int | None = None,
    queue_limit: int | None = None,
) -> dict[str, Any]:
    """
    Convert discovered markets into tiered coverage candidates.

    This is intentionally broader than the startup top-N backfill path. It
    creates state for every analyzable discovered market, lets the allocator
    assign a coverage tier, and then queues bounded work for markets that need
    REST recent-trade or OHLCV coverage.
    """

    ensure_source_catalog(db)
    now = datetime.now(timezone.utc)
    sources = configured_stream_sources()
    limit_n = max(1, min(int(limit or settings.MARKET_ACTIVATION_BATCH_SIZE), 50_000))
    queue_limit_n = max(0, min(int(queue_limit if queue_limit is not None else settings.MARKET_ACTIVATION_QUEUE_LIMIT), 5000))
    health_map = {row.source: row for row in db.query(DataSourceHealth).all()}
    status_map = {
        (row.exchange, row.symbol): row
        for row in db.query(AssetDataStatus).filter(AssetDataStatus.exchange.in_(sources)).all()
    }
    target_map = {
        (row.exchange, row.symbol): row
        for row in db.query(StreamTarget).filter(StreamTarget.exchange.in_(sources)).all()
    }

    markets = (
        db.query(ExchangeMarket)
        .filter(
            ExchangeMarket.exchange.in_(sources),
            ExchangeMarket.active.is_(True),
            ExchangeMarket.spot.is_(True),
            ExchangeMarket.is_analyzable.is_(True),
        )
        .order_by(ExchangeMarket.exchange.asc(), ExchangeMarket.db_symbol.asc())
        .limit(limit_n)
        .all()
    )

    activated = 0
    unavailable = 0
    created_status = 0
    created_targets = 0
    for market in markets:
        symbol = market.db_symbol.upper()
        health = health_map.get(market.exchange)
        unavailable_reason = source_unavailable_reason(health)

        status = status_map.get((market.exchange, symbol))
        if status is None:
            status = AssetDataStatus(
                exchange=market.exchange,
                symbol=symbol,
                base_symbol=market.base,
                status="unsupported" if unavailable_reason else "warming_up",
                is_supported=not bool(unavailable_reason),
                is_analyzable=True,
                row_count=0,
                last_failure_reason=unavailable_reason,
                metadata_json={},
            )
            db.add(status)
            status_map[(market.exchange, symbol)] = status
            created_status += 1
        elif unavailable_reason:
            status.status = "unsupported"
            status.is_supported = False
            status.is_analyzable = True
            status.last_failure_reason = unavailable_reason
            status.last_backfill_failed_at = now
        elif status.status == "unsupported" and _was_source_unavailable(status.last_failure_reason):
            status.status = "warming_up"
            status.is_supported = True
            status.is_analyzable = True
            status.last_failure_reason = None

        status.metadata_json = {
            **(status.metadata_json or {}),
            "coverage_activation": {
                "last_evaluated_at": now.isoformat(),
                "source_unavailable": bool(unavailable_reason),
                "source_unavailable_reason": unavailable_reason,
            },
        }

        target = target_map.get((market.exchange, symbol))
        if target is None:
            target = StreamTarget(
                exchange=market.exchange,
                symbol=symbol,
                base=market.base,
                quote=market.quote,
                source_type="cex",
                status="candidate",
                coverage_tier="ohlcv_only",
                capacity_state="normal",
                score=0.0,
                active=False,
                user_preference="neutral",
            )
            db.add(target)
            target_map[(market.exchange, symbol)] = target
            created_targets += 1
        target.base = market.base
        target.quote = market.quote
        target.source_type = "cex"
        target.reason = unavailable_reason or target.reason
        if unavailable_reason:
            target.active = False
            target.status = "candidate"
            target.coverage_tier = "ohlcv_only"
            target.capacity_state = "source_unavailable"
            target.score_details_json = {
                **(target.score_details_json or {}),
                "availability_reason": unavailable_reason,
            }
            unavailable += 1
        else:
            activated += 1

    db.flush()
    allocation = allocate_stream_targets(db, publish_commands=False)
    queued = _queue_tier_work(db, queue_work=queue_work, queue_limit=queue_limit_n, now=now)
    coverage = tiered_coverage_summary(db)
    return {
        "status": "ok",
        "evaluated": len(markets),
        "activated": activated,
        "unavailable": unavailable,
        "created_status": created_status,
        "created_targets": created_targets,
        "allocation": allocation,
        "queued": queued,
        "coverage": coverage,
    }


def tiered_coverage_summary(db: Session) -> dict[str, Any]:
    by_tier = {
        tier: int(count)
        for tier, count in db.query(StreamTarget.coverage_tier, func.count(StreamTarget.id))
        .group_by(StreamTarget.coverage_tier)
        .all()
    }
    by_exchange_tier: dict[str, dict[str, int]] = {}
    for exchange, tier, count in (
        db.query(StreamTarget.exchange, StreamTarget.coverage_tier, func.count(StreamTarget.id))
        .group_by(StreamTarget.exchange, StreamTarget.coverage_tier)
        .all()
    ):
        by_exchange_tier.setdefault(exchange, {})[tier] = int(count)
    return {
        "by_tier": by_tier,
        "by_exchange_tier": by_exchange_tier,
        "total_targets": sum(by_tier.values()),
    }


def _queue_tier_work(
    db: Session,
    *,
    queue_work: bool,
    queue_limit: int,
    now: datetime,
) -> dict[str, Any]:
    if not queue_work or queue_limit <= 0:
        return {"enabled": queue_work, "queued": 0, "tasks_sample": []}

    targets = (
        db.query(StreamTarget)
        .filter(
            StreamTarget.source_type == "cex",
            StreamTarget.user_preference != "blocked",
            StreamTarget.coverage_tier.in_(["tick_stream", "quote_stream", "rest_gap_fill", "ohlcv_only"]),
        )
        .order_by(StreamTarget.score.desc(), StreamTarget.exchange.asc(), StreamTarget.symbol.asc())
        .limit(queue_limit * 4)
        .all()
    )
    queued = []
    for target in targets:
        if len(queued) >= queue_limit:
            break
        status = (
            db.query(AssetDataStatus)
            .filter(AssetDataStatus.exchange == target.exchange, AssetDataStatus.symbol == target.symbol)
            .first()
        )
        if _skip_queue(status, now):
            continue
        if target.coverage_tier == "rest_gap_fill":
            task = celery_app.send_task(
                "celery_worker.tasks.ingest_recent_trades_task",
                kwargs={"symbol": target.symbol, "exchange_id": target.exchange, "limit": 500},
            )
            kind = "recent_trades"
        else:
            task = celery_app.send_task(
                "celery_worker.tasks.backfill_historical_candles",
                kwargs={
                    "symbol": target.symbol,
                    "exchange_id": target.exchange,
                    "timeframe": settings.MARKET_ACTIVATION_TIMEFRAME,
                    "days": settings.MARKET_ACTIVATION_BACKFILL_DAYS,
                },
            )
            kind = "ohlcv"
        if status is None:
            base = target.base or target.symbol.split("-", 1)[0]
            status = AssetDataStatus(
                exchange=target.exchange,
                symbol=target.symbol,
                base_symbol=base,
            )
            db.add(status)
        status.status = "backfill_pending"
        status.is_supported = True
        status.is_analyzable = True
        status.last_backfill_task_id = task.id
        status.last_backfill_started_at = now
        status.last_failure_reason = None
        status.metadata_json = {
            **(status.metadata_json or {}),
            "coverage_activation": {
                "queued_at": now.isoformat(),
                "queued_kind": kind,
                "coverage_tier": target.coverage_tier,
            },
        }
        queued.append({"exchange": target.exchange, "symbol": target.symbol, "kind": kind, "task_id": task.id})
    db.flush()
    return {"enabled": True, "queued": len(queued), "tasks_sample": queued[:20]}


def _skip_queue(status: AssetDataStatus | None, now: datetime) -> bool:
    if status is None:
        return False
    if status.status in {"unsupported", "not_applicable", "backfill_pending"}:
        return True
    if status.status == "ready" and int(status.row_count or 0) >= READY_CANDLE_COUNT:
        latest = status.latest_candle_at
        if latest is None:
            return False
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return now - latest < timedelta(hours=6)
    return False


def _was_source_unavailable(reason: str | None) -> bool:
    if not reason:
        return False
    value = reason.lower()
    return "source appears region-blocked" in value or "source unavailable" in value or "source is disabled" in value
