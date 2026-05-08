from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.instrument import Price
from app.models.market import MarketTrade
from app.models.ticks import Asset, Tick


@dataclass
class CandleLoadResult:
    df: pd.DataFrame
    requested_bucket_seconds: int
    bucket_seconds: int
    source: str
    resolution: str = "unknown"


def load_candles_df(
    db: Session,
    exchange: str,
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str,
    source: str = "auto",
    max_points: int = 50_000,
) -> CandleLoadResult:
    exchange = exchange.strip().lower()
    symbol = symbol.strip().upper()

    start_dt = _to_utc(start)
    end_dt = _to_utc(end)
    if start_dt > end_dt:
        raise ValueError("start must be <= end")

    requested_bucket_seconds = parse_timeframe_seconds(timeframe)
    range_seconds = max(1.0, (end_dt - start_dt).total_seconds())
    bucket_seconds = int(requested_bucket_seconds)

    if max_points > 0 and range_seconds / bucket_seconds > max_points:
        bucket_seconds = int(math.ceil(range_seconds / max_points))

    candles: list[dict] = []
    source_used = "none"
    source_key = (source or "auto").strip().lower()

    def _load(kind: str) -> list[dict]:
        if kind == "ticks":
            return _load_ticks(db, exchange, symbol, start_dt, end_dt, bucket_seconds)
        if kind == "market_trades":
            return _load_market_trades(db, exchange, symbol, start_dt, end_dt, bucket_seconds)
        if kind == "prices":
            return _load_prices(db, exchange, symbol, start_dt, end_dt, timeframe)
        return []

    if source_key == "auto":
        for kind in ("ticks", "market_trades", "prices"):
            candles = _load(kind)
            if candles:
                source_used = kind
                break
    else:
        candles = _load(source_key)
        source_used = source_key

    df = _candles_to_df(candles)
    return CandleLoadResult(
        df=df,
        requested_bucket_seconds=requested_bucket_seconds,
        bucket_seconds=bucket_seconds,
        source=source_used,
        resolution=_resolution_for(source_used, bucket_seconds),
    )


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_timeframe_seconds(timeframe: str) -> int:
    tf = (timeframe or "").strip().lower()
    if not tf:
        raise ValueError("timeframe is required")

    unit = tf[-1]
    try:
        value = int(tf[:-1])
    except ValueError as exc:
        raise ValueError(f"Invalid timeframe '{timeframe}'") from exc

    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400

    raise ValueError(f"Invalid timeframe '{timeframe}'")


def _timeframe_rule(timeframe: str) -> str:
    tf = timeframe.strip().lower()
    unit = tf[-1]
    value = int(tf[:-1])
    if unit == "s":
        return f"{value}S"
    if unit == "m":
        return f"{value}min"
    if unit == "h":
        return f"{value}H"
    if unit == "d":
        return f"{value}D"
    raise ValueError(f"Invalid timeframe '{timeframe}'")


def _load_ticks(
    db: Session,
    exchange: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
) -> list[dict]:
    asset = (
        db.query(Asset)
        .filter(Asset.exchange == exchange, Asset.symbol == symbol)
        .first()
    )
    if not asset:
        return []

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        if not _is_recent_window(end_dt):
            for view_name, view_bucket_seconds in _rollup_candidates(bucket_seconds):
                candles = _load_tick_rollup(
                    db,
                    asset_id=asset.id,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    bucket_seconds=max(bucket_seconds, view_bucket_seconds),
                    view_name=view_name,
                )
                if candles:
                    return candles

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
        rows = (
            db.execute(
                sql,
                {
                    "bucket": bucket_interval,
                    "asset_id": asset.id,
                    "start": start_dt,
                    "end": end_dt,
                },
            )
            .mappings()
            .all()
        )
        return _rows_to_candles(rows)

    rows = (
        db.query(Tick)
        .filter(
            Tick.asset_id == asset.id,
            Tick.time >= start_dt,
            Tick.time <= end_dt,
        )
        .order_by(Tick.time.asc())
        .all()
    )
    return _bucket_rows(
        rows,
        bucket_seconds=bucket_seconds,
        ts_attr="time",
        price_attr="price",
        volume_attr="volume",
    )


def _load_tick_rollup(
    db: Session,
    *,
    asset_id: int,
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
    view_name: str,
) -> list[dict]:
    bucket_interval = f"{bucket_seconds} seconds"
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
        return []
    return _rows_to_candles(rows)


def _rollup_candidates(bucket_seconds: int) -> list[tuple[str, int]]:
    if bucket_seconds >= 300:
        return [("ticks_5m", 300), ("ticks_1m", 60)]
    if bucket_seconds >= 60:
        return [("ticks_1m", 60)]
    if bucket_seconds >= 5:
        return [("ticks_5s", 5)]
    if bucket_seconds >= 3:
        return [("ticks_3s", 3)]
    return [("ticks_1s", 1)]


def _is_recent_window(end_dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    return now - end_dt <= pd.Timedelta(minutes=5).to_pytimedelta()


def _resolution_for(source: str, bucket_seconds: int) -> str:
    if source == "ticks" and bucket_seconds >= 60:
        return "timescale_tick_rollup_or_raw"
    if source == "ticks":
        return "raw_ticks"
    if source == "market_trades":
        return "compatibility_trades"
    if source == "prices":
        return "ohlcv_candles"
    return "none"


def _load_market_trades(
    db: Session,
    exchange: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    bucket_seconds: int,
) -> list[dict]:
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
        return _rows_to_candles(rows)

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
    return _bucket_rows(
        rows,
        bucket_seconds=bucket_seconds,
        ts_attr="timestamp",
        price_attr="price",
        volume_attr="amount",
    )


def _load_prices(
    db: Session,
    exchange: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    timeframe: str,
) -> list[dict]:
    rows = (
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
    if not rows:
        return []

    df = pd.DataFrame(
        [
            {
                "timestamp": _to_utc(row.timestamp),
                "open": float(row.open or 0.0),
                "high": float(row.high or 0.0),
                "low": float(row.low or 0.0),
                "close": float(row.close or 0.0),
                "volume": float(row.volume or 0.0),
            }
            for row in rows
        ]
    )

    df = df.sort_values("timestamp").set_index("timestamp")
    rule = _timeframe_rule(timeframe)
    resampled = df.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    resampled = resampled.reset_index()

    return [
        {
            "timestamp": ts.to_pydatetime().isoformat(),
            "open": float(open_p),
            "high": float(high_p),
            "low": float(low_p),
            "close": float(close_p),
            "volume": float(volume),
            "trades": 0,
        }
        for ts, open_p, high_p, low_p, close_p, volume in resampled.itertuples(index=False)
    ]


def _rows_to_candles(rows) -> list[dict]:
    candles: list[dict] = []
    for row in rows:
        bucket = row.get("bucket")
        if bucket is None:
            continue
        open_p = row.get("open")
        high_p = row.get("high")
        low_p = row.get("low")
        close_p = row.get("close")
        if open_p is None or high_p is None or low_p is None or close_p is None:
            continue
        candles.append(
            {
                "timestamp": _to_utc(bucket).isoformat(),
                "open": float(open_p),
                "high": float(high_p),
                "low": float(low_p),
                "close": float(close_p),
                "volume": float(row.get("volume") or 0.0),
                "trades": int(row.get("trades") or 0),
            }
        )
    return candles


def _bucket_rows(
    rows,
    bucket_seconds: int,
    ts_attr: str,
    price_attr: str,
    volume_attr: str,
) -> list[dict]:
    buckets: dict[int, dict] = {}
    for row in rows:
        ts = getattr(row, ts_attr)
        ts = _to_utc(ts)
        bucket_epoch = int(ts.timestamp() // bucket_seconds) * bucket_seconds
        price = float(getattr(row, price_attr))
        volume = float(getattr(row, volume_attr))
        item = buckets.get(bucket_epoch)
        if item is None:
            buckets[bucket_epoch] = {
                "timestamp": datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
                "trades": 1,
            }
        else:
            item["high"] = max(item["high"], price)
            item["low"] = min(item["low"], price)
            item["close"] = price
            item["volume"] += volume
            item["trades"] += 1
    return [buckets[key] for key in sorted(buckets.keys())]


def _candles_to_df(candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


