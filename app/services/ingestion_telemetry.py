from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.research import DataSourceHealth
from app.redis_client import RedisClient
from app.services.data_sources import ensure_source_catalog


STREAM_KEYS = ("market_trades", "market_quotes")
WRITER_GROUP = "trade_writers"


async def collect_ingestion_telemetry(db: Session, *, redis=None) -> dict[str, Any]:
    """
    Sample Redis/Timescale ingestion pressure and persist the latest snapshot.

    The allocator intentionally reads this persisted snapshot instead of opening
    Redis during every scoring pass. That keeps rebalancing deterministic in API
    calls and lets Celery own the operational sampling cadence.
    """

    ensure_source_catalog(db)
    redis = redis or RedisClient.get_redis()
    now = datetime.now(timezone.utc)

    redis_metrics: dict[str, Any] = {}
    total_length = 0
    total_pending = 0
    for stream_key in STREAM_KEYS:
        length = await _safe_xlen(redis, stream_key)
        pending = await _safe_xpending(redis, stream_key, WRITER_GROUP)
        redis_metrics[stream_key] = {"length": length, "pending": pending}
        total_length += length
        total_pending += pending

    writer_lag = _writer_lag_seconds(db, now)
    timescale = _timescale_health(db)
    ensure_source_catalog(db)
    pressure = _pressure_score(
        pending=total_pending,
        stream_length=total_length,
        writer_lag_seconds=writer_lag,
        timescale=timescale,
    )

    metadata = {
        "redis": redis_metrics,
        "timescale": timescale,
        "pressure_inputs": {
            "pending": total_pending,
            "stream_length": total_length,
            "writer_lag_seconds": writer_lag,
        },
    }

    rows = db.query(DataSourceHealth).all()
    for row in rows:
        row.redis_stream_length = total_length
        row.redis_pending_messages = total_pending
        row.writer_lag_seconds = writer_lag
        row.db_pressure = pressure
        row.last_telemetry_at = now
        row.metadata_json = {**(row.metadata_json or {}), "ingestion_telemetry": metadata}
    db.flush()

    return {
        "status": "ok",
        "sampled_at": now.isoformat(),
        "redis": redis_metrics,
        "timescale": timescale,
        "writer_lag_seconds": writer_lag,
        "db_pressure": pressure,
        "sources_updated": len(rows),
    }


def latest_capacity_snapshot(db: Session) -> dict[str, Any]:
    rows = db.query(DataSourceHealth).all()
    if not rows:
        return {
            "state": "unknown",
            "db_pressure": 0.0,
            "redis_pending_messages": 0,
            "writer_lag_seconds": None,
            "reason": "No source health rows have been sampled yet.",
        }

    pressure = max(float(row.db_pressure or 0.0) for row in rows)
    pending = max(int(row.redis_pending_messages or 0) for row in rows)
    lag_values = [float(row.writer_lag_seconds) for row in rows if row.writer_lag_seconds is not None]
    writer_lag = max(lag_values) if lag_values else None
    state = "normal"
    reason = "Ingestion capacity is within configured thresholds."
    if pressure >= float(settings.STREAM_DB_PRESSURE_HIGH_WATERMARK):
        state = "constrained"
        reason = "Ingestion pressure is above the high watermark; demote marginal streams."

    return {
        "state": state,
        "db_pressure": round(pressure, 4),
        "redis_pending_messages": pending,
        "writer_lag_seconds": writer_lag,
        "reason": reason,
    }


async def _safe_xlen(redis, stream_key: str) -> int:
    try:
        return int(await redis.xlen(stream_key))
    except Exception:
        return 0


async def _safe_xpending(redis, stream_key: str, group: str) -> int:
    try:
        value = await redis.xpending(stream_key, group)
    except Exception:
        return 0
    if isinstance(value, dict):
        return int(value.get("pending") or value.get("count") or 0)
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _writer_lag_seconds(db: Session, now: datetime) -> float | None:
    rows = db.query(DataSourceHealth).filter(DataSourceHealth.last_event_at.isnot(None)).all()
    if not rows:
        return None
    lag = 0.0
    for row in rows:
        event_at = row.last_event_at
        if event_at is None:
            continue
        if event_at.tzinfo is None:
            event_at = event_at.replace(tzinfo=timezone.utc)
        lag = max(lag, (now - event_at).total_seconds())
    return max(0.0, lag)


def _timescale_health(db: Session) -> dict[str, Any]:
    if db.get_bind().dialect.name != "postgresql":
        return {"available": False, "reason": "non-postgresql dialect"}
    try:
        hypertables = (
            db.execute(
                text(
                    """
                    SELECT hypertable_name, num_chunks, compression_enabled
                    FROM timescaledb_information.hypertables
                    WHERE hypertable_name IN ('ticks', 'market_trades', 'market_quotes')
                    ORDER BY hypertable_name
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception as exc:
        db.rollback()
        return {"available": False, "reason": str(exc)}

    try:
        jobs = (
            db.execute(
                text(
                    """
                    SELECT hypertable_name, job_id, proc_name, last_run_status
                    FROM timescaledb_information.jobs
                    WHERE hypertable_name IN (
                      'ticks', 'market_trades', 'market_quotes',
                      'ticks_1m', 'ticks_5m', 'market_quotes_1m', 'market_quotes_5m'
                    )
                    ORDER BY hypertable_name, job_id
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        jobs = []

    return {
        "available": True,
        "hypertables": [dict(row) for row in hypertables],
        "jobs": [dict(row) for row in jobs],
    }


def _pressure_score(
    *,
    pending: int,
    stream_length: int,
    writer_lag_seconds: float | None,
    timescale: dict[str, Any],
) -> float:
    pending_score = min(1.0, pending / max(1, int(settings.STREAM_REDIS_MAX_PENDING)))
    length_score = min(1.0, stream_length / max(1, int(settings.STREAM_REDIS_MAX_PENDING) * 2))
    lag_score = 0.0
    if writer_lag_seconds is not None:
        lag_score = min(1.0, writer_lag_seconds / max(1, int(settings.STREAM_WRITER_MAX_LAG_SECONDS)))
    timescale_score = 0.0 if timescale.get("available") else 0.1
    return round(max(pending_score, length_score, lag_score, timescale_score), 4)
