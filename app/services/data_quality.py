from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.ticks import Tick, Asset
from app.models.market import MarketTrade

def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _align_bucket_time(dt: datetime, bucket_seconds: int) -> datetime:
    epoch = int(dt.timestamp() // bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(epoch, tz=timezone.utc)

def _validate_gap_request(
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
    max_points: int,
) -> tuple[datetime, datetime, int]:
    if bucket_seconds < 1:
        raise HTTPException(status_code=400, detail="bucket_seconds must be >= 1")
    aligned_start = _align_bucket_time(start_dt, bucket_seconds)
    aligned_end = _align_bucket_time(end_dt, bucket_seconds)
    if aligned_start > aligned_end:
        raise HTTPException(status_code=400, detail="Invalid time range after alignment")
    total_buckets = int((aligned_end - aligned_start).total_seconds() // bucket_seconds) + 1
    if total_buckets > max_points:
        raise HTTPException(
            status_code=400,
            detail="Range too large for bucket_seconds; reduce range or increase bucket_seconds.",
        )
    return aligned_start, aligned_end, total_buckets

def _coalesce_gap_ranges(missing: list[datetime], bucket_seconds: int) -> list[dict]:
    if not missing:
        return []
    missing_sorted = sorted(missing)
    ranges: list[dict] = []
    start = missing_sorted[0]
    prev = start
    count = 1
    for ts in missing_sorted[1:]:
        if int((ts - prev).total_seconds()) == bucket_seconds:
            prev = ts
            count += 1
            continue
        ranges.append(
            {
                "start": start.isoformat(),
                "end": (prev + timedelta(seconds=bucket_seconds)).isoformat(),
                "buckets": count,
            }
        )
        start = ts
        prev = ts
        count = 1
    ranges.append(
        {
            "start": start.isoformat(),
            "end": (prev + timedelta(seconds=bucket_seconds)).isoformat(),
            "buckets": count,
        }
    )
    return ranges

def _bucket_missing_python(
    rows: list,
    *,
    time_getter,
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
) -> list[datetime]:
    counts: dict[int, int] = {}
    for row in rows:
        ts = time_getter(row)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        bucket_epoch = int(ts.timestamp() // bucket_seconds) * bucket_seconds
        counts[bucket_epoch] = counts.get(bucket_epoch, 0) + 1

    missing: list[datetime] = []
    bucket_epoch = int(start_dt.timestamp())
    end_epoch = int(end_dt.timestamp())
    while bucket_epoch <= end_epoch:
        if counts.get(bucket_epoch, 0) == 0:
            missing.append(datetime.fromtimestamp(bucket_epoch, tz=timezone.utc))
        bucket_epoch += bucket_seconds
    return missing

def _fetch_gap_buckets_postgres(
    db: Session,
    *,
    source: str,
    asset_id: int | None,
    exchange: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
) -> list[tuple[datetime, int]]:
    bucket_interval = f"{bucket_seconds} seconds"
    if source == "ticks":
        sql = text(
            """
            WITH buckets AS (
                SELECT generate_series(:start, :end, CAST(:bucket AS interval)) AS bucket
            ),
            counts AS (
                SELECT time_bucket(CAST(:bucket AS interval), time) AS bucket, COUNT(*) AS trades
                FROM ticks
                WHERE asset_id = :asset_id
                  AND time >= :start
                  AND time <= :end
                GROUP BY bucket
            )
            SELECT b.bucket AS bucket, COALESCE(c.trades, 0) AS trades
            FROM buckets b
            LEFT JOIN counts c ON b.bucket = c.bucket
            ORDER BY b.bucket ASC
            """
        )
        params = {
            "bucket": bucket_interval,
            "asset_id": asset_id,
            "start": start_dt,
            "end": end_dt,
        }
    elif source == "market_trades":
        sql = text(
            """
            WITH buckets AS (
                SELECT generate_series(:start, :end, CAST(:bucket AS interval)) AS bucket
            ),
            counts AS (
                SELECT time_bucket(CAST(:bucket AS interval), timestamp) AS bucket, COUNT(*) AS trades
                FROM market_trades
                WHERE exchange = :exchange
                  AND symbol = :symbol
                  AND timestamp >= :start
                  AND timestamp <= :end
                GROUP BY bucket
            )
            SELECT b.bucket AS bucket, COALESCE(c.trades, 0) AS trades
            FROM buckets b
            LEFT JOIN counts c ON b.bucket = c.bucket
            ORDER BY b.bucket ASC
            """
        )
        params = {
            "bucket": bucket_interval,
            "exchange": exchange,
            "symbol": symbol,
            "start": start_dt,
            "end": end_dt,
        }
    else:
        sql = text(
            f"""
            WITH buckets AS (
                SELECT generate_series(:start, :end, CAST(:bucket AS interval)) AS bucket
            ),
            counts AS (
                SELECT time_bucket(CAST(:bucket AS interval), bucket) AS bucket, SUM(trades) AS trades
                FROM {source}
                WHERE asset_id = :asset_id
                  AND bucket >= :start
                  AND bucket <= :end
                GROUP BY bucket
            )
            SELECT b.bucket AS bucket, COALESCE(c.trades, 0) AS trades
            FROM buckets b
            LEFT JOIN counts c ON b.bucket = c.bucket
            ORDER BY b.bucket ASC
            """
        )
        params = {
            "bucket": bucket_interval,
            "asset_id": asset_id,
            "start": start_dt,
            "end": end_dt,
        }

    rows = (
        db.execute(sql, params)
        .mappings()
        .all()
    )
    results: list[tuple[datetime, int]] = []
    for row in rows:
        bucket = row.get("bucket")
        trades = row.get("trades")
        if bucket is None:
            continue
        results.append((bucket, int(trades or 0)))
    return results

def detect_gaps_data(
    db: Session,
    *,
    exchange: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
    max_points: int,
    source: str,
) -> dict:
    aligned_start, aligned_end, total_buckets = _validate_gap_request(
        start_dt, end_dt, bucket_seconds, max_points
    )

    dialect = db.get_bind().dialect.name
    
    asset_id = (
        db.query(Asset.id)
        .filter(Asset.exchange == exchange, Asset.symbol == symbol)
        .scalar()
    )

    source = (source or "auto").strip().lower()
    allowed_sources = {
        "auto",
        "ticks",
        "ticks_1s",
        "ticks_3s",
        "ticks_5s",
        "ticks_7s",
        "market_trades",
    }
    if source not in allowed_sources:
        raise HTTPException(status_code=400, detail="Unsupported source value.")

    def _has_ticks_data() -> bool:
        if asset_id is None:
            return False
        if dialect == "postgresql":
            return (
                db.execute(
                    text(
                        """
                        SELECT 1 FROM ticks
                        WHERE asset_id = :asset_id
                          AND time >= :start
                          AND time <= :end
                        LIMIT 1
                        """
                    ),
                    {"asset_id": asset_id, "start": aligned_start, "end": aligned_end},
                ).scalar()
                is not None
            )
        return (
            db.query(Tick.id)
            .filter(
                Tick.asset_id == asset_id,
                Tick.time >= aligned_start,
                Tick.time <= aligned_end,
            )
            .first()
            is not None
        )

    def _has_market_trades() -> bool:
        if dialect == "postgresql":
            return (
                db.execute(
                    text(
                        """
                        SELECT 1 FROM market_trades
                        WHERE exchange = :exchange
                          AND symbol = :symbol
                          AND timestamp >= :start
                          AND timestamp <= :end
                        LIMIT 1
                        """
                    ),
                    {
                        "exchange": exchange,
                        "symbol": symbol,
                        "start": aligned_start,
                        "end": aligned_end,
                    },
                ).scalar()
                is not None
            )
        return (
            db.query(MarketTrade.id)
            .filter(
                MarketTrade.exchange == exchange,
                MarketTrade.symbol == symbol,
                MarketTrade.timestamp >= aligned_start,
                MarketTrade.timestamp <= aligned_end,
            )
            .first()
            is not None
        )

    def _has_view_data(view_name: str) -> bool:
        if asset_id is None:
            return False
        try:
            return (
                db.execute(
                    text(
                        f"""
                        SELECT 1 FROM {view_name}
                        WHERE asset_id = :asset_id
                          AND bucket >= :start
                          AND bucket <= :end
                        LIMIT 1
                        """
                    ),
                    {"asset_id": asset_id, "start": aligned_start, "end": aligned_end},
                ).scalar()
                is not None
            )
        except Exception:
            return False

    selected_source = source
    source_granularity = None
    if source == "auto":
        selected_source = "none"
        if _has_ticks_data():
            selected_source = "ticks"
        elif dialect == "postgresql" and asset_id is not None:
            for view_name, granularity in (
                ("ticks_1s", 1),
                ("ticks_3s", 3),
                ("ticks_5s", 5),
                ("ticks_7s", 7),
            ):
                if _has_view_data(view_name):
                    selected_source = view_name
                    source_granularity = granularity
                    break
        if selected_source == "none" and _has_market_trades():
            selected_source = "market_trades"
    elif selected_source.startswith("ticks_"):
        if selected_source == "ticks_1s":
            source_granularity = 1
        elif selected_source == "ticks_3s":
            source_granularity = 3
        elif selected_source == "ticks_5s":
            source_granularity = 5
        elif selected_source == "ticks_7s":
            source_granularity = 7

    if selected_source.startswith("ticks_") and dialect != "postgresql":
        raise HTTPException(
            status_code=400,
            detail="Aggregate gap detection requires PostgreSQL/TimescaleDB.",
        )

    missing: list[datetime] = []
    buckets = None
    if selected_source == "none":
        missing = [
            aligned_start + timedelta(seconds=bucket_seconds * idx)
            for idx in range(total_buckets)
        ]
    else:
        if dialect == "postgresql":
            try:
                buckets = _fetch_gap_buckets_postgres(
                    db,
                    source=selected_source,
                    asset_id=asset_id,
                    exchange=exchange,
                    symbol=symbol,
                    start_dt=aligned_start,
                    end_dt=aligned_end,
                    bucket_seconds=bucket_seconds,
                )
                missing = [bucket for bucket, trades in buckets if trades == 0]
            except Exception:
                buckets = None

        if not missing and buckets is None:
            if selected_source == "ticks":
                if asset_id is None:
                    raise HTTPException(status_code=404, detail="No asset found for symbol.")
                rows = (
                    db.query(Tick)
                    .filter(
                        Tick.asset_id == asset_id,
                        Tick.time >= aligned_start,
                        Tick.time <= aligned_end,
                    )
                    .all()
                )
                missing = _bucket_missing_python(
                    rows,
                    time_getter=lambda row: row.time,
                    start_dt=aligned_start,
                    end_dt=aligned_end,
                    bucket_seconds=bucket_seconds,
                )
            elif selected_source == "market_trades":
                rows = (
                    db.query(MarketTrade)
                    .filter(
                        MarketTrade.exchange == exchange,
                        MarketTrade.symbol == symbol,
                        MarketTrade.timestamp >= aligned_start,
                        MarketTrade.timestamp <= aligned_end,
                    )
                    .all()
                )
                missing = _bucket_missing_python(
                    rows,
                    time_getter=lambda row: row.timestamp,
                    start_dt=aligned_start,
                    end_dt=aligned_end,
                    bucket_seconds=bucket_seconds,
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Gap detection failed for aggregate source.",
                )

    gap_ranges = _coalesce_gap_ranges(missing, bucket_seconds)
    missing_count = len(missing)
    covered_buckets = max(0, total_buckets - missing_count)
    
    return {
        "aligned_start": aligned_start,
        "aligned_end": aligned_end,
        "total_buckets": total_buckets,
        "covered_buckets": covered_buckets,
        "missing_buckets": missing_count,
        "missing": missing,
        "gaps": gap_ranges,
        "source": selected_source,
        "source_granularity_seconds": source_granularity,
    }
