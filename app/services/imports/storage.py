from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models.ticks import Asset, Tick, TickFocus
from app.streaming.symbols import parse_symbol
from app.services.imports.types import TickRecord


def normalize_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if "/" in raw:
        base, quote = raw.split("/", 1)
        return f"{base.strip()}-{quote.strip()}"
    return raw


def _normalize_time(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_or_create_asset(
    db: Session,
    *,
    symbol: str,
    exchange: str,
    tick_precision: int | None = None,
) -> Asset:
    symbol = normalize_symbol(symbol)
    exchange = exchange.strip().lower()

    parsed = parse_symbol(symbol)
    asset = (
        db.query(Asset)
        .filter(Asset.symbol == symbol, Asset.exchange == exchange)
        .one_or_none()
    )
    if asset:
        if tick_precision is not None and asset.tick_precision != tick_precision:
            asset.tick_precision = tick_precision
        return asset

    asset = Asset(
        symbol=symbol,
        exchange=exchange,
        base=parsed.base,
        quote=parsed.quote,
        tick_precision=tick_precision,
        active=True,
    )
    db.add(asset)
    db.flush()
    return asset


def bulk_insert_ticks(
    db: Session,
    *,
    asset_id: int,
    rows: Iterable[TickRecord],
    ingest_source: str | None = None,
    owner_id: str | None = None,
    focus: bool = False,
    focus_reason: str | None = None,
    focus_score: float | None = None,
) -> int:
    rows = list(rows)
    if not rows:
        return 0

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return _copy_ticks(
            db,
            asset_id=asset_id,
            rows=rows,
            ingest_source=ingest_source,
            owner_id=owner_id,
            focus=focus,
            focus_reason=focus_reason,
            focus_score=focus_score,
        )

    objects = []
    now = datetime.now(timezone.utc)
    if focus:
        for row in rows:
            ts = _normalize_time(row.time)
            objects.append(
                TickFocus(
                    time=ts,
                    asset_id=asset_id,
                    price=row.price,
                    volume=row.volume,
                    side=row.side,
                    exchange_trade_id=row.exchange_trade_id,
                    received_at=now,
                    ingest_source=ingest_source,
                    focus_reason=focus_reason,
                    focus_score=focus_score,
                    owner_id=owner_id,
                )
            )
    else:
        if dialect == "sqlite":
            rows_payload = []
            for row in rows:
                ts = _normalize_time(row.time)
                rows_payload.append(
                    {
                        "time": ts,
                        "asset_id": asset_id,
                        "price": row.price,
                        "volume": row.volume,
                        "side": row.side,
                        "exchange_trade_id": row.exchange_trade_id,
                        "received_at": now,
                        "ingest_source": ingest_source,
                        "is_aggregated": row.is_aggregated,
                        "owner_id": owner_id,
                    }
                )
            stmt = insert(Tick).values(rows_payload).prefix_with("OR IGNORE")
            result = db.execute(stmt)
            return int(result.rowcount or 0)

        for row in rows:
            ts = _normalize_time(row.time)
            objects.append(
                Tick(
                    time=ts,
                    asset_id=asset_id,
                    price=row.price,
                    volume=row.volume,
                    side=row.side,
                    exchange_trade_id=row.exchange_trade_id,
                    received_at=now,
                    ingest_source=ingest_source,
                    is_aggregated=row.is_aggregated,
                    owner_id=owner_id,
                )
            )
    db.bulk_save_objects(objects)
    return len(objects)


def _copy_ticks(
    db: Session,
    *,
    asset_id: int,
    rows: list[TickRecord],
    ingest_source: str | None,
    owner_id: str | None,
    focus: bool,
    focus_reason: str | None,
    focus_score: float | None,
) -> int:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    now = datetime.now(timezone.utc)

    if focus:
        for row in rows:
            ts = _normalize_time(row.time)
            writer.writerow(
                [
                    ts.isoformat(),
                    asset_id,
                    row.price,
                    row.volume,
                    row.side,
                    row.exchange_trade_id,
                    now.isoformat(),
                    ingest_source,
                    focus_reason,
                    focus_score,
                    owner_id,
                ]
            )
        columns = (
            "time,asset_id,price,volume,side,exchange_trade_id,received_at,"
            "ingest_source,focus_reason,focus_score,owner_id"
        )
        target = "ticks_focus"
    else:
        for row in rows:
            ts = _normalize_time(row.time)
            writer.writerow(
                [
                    ts.isoformat(),
                    asset_id,
                    row.price,
                    row.volume,
                    row.side,
                    row.exchange_trade_id,
                    now.isoformat(),
                    ingest_source,
                    row.is_aggregated,
                    owner_id,
                ]
            )
        columns = (
            "time,asset_id,price,volume,side,exchange_trade_id,received_at,"
            "ingest_source,is_aggregated,owner_id"
        )
        target = "ticks"

    buffer.seek(0)

    conn = db.connection()
    raw = conn.connection
    cursor = raw.cursor()
    if focus:
        cursor.copy_expert(
            f"COPY {target} ({columns}) FROM STDIN WITH (FORMAT csv)",
            buffer,
        )
        cursor.close()
        return len(rows)

    cursor.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS ticks_stage (
            time timestamptz,
            asset_id integer,
            price double precision,
            volume double precision,
            side text,
            exchange_trade_id text,
            received_at timestamptz,
            ingest_source text,
            is_aggregated boolean,
            owner_id text
        ) ON COMMIT DROP;
        """
    )
    cursor.execute("TRUNCATE ticks_stage;")
    cursor.copy_expert(
        f"COPY ticks_stage ({columns}) FROM STDIN WITH (FORMAT csv)",
        buffer,
    )
    cursor.execute(
        """
        INSERT INTO ticks (time, asset_id, price, volume, side, exchange_trade_id, received_at,
                           ingest_source, is_aggregated, owner_id)
        SELECT time, asset_id, price, volume, side, exchange_trade_id, received_at,
               ingest_source, is_aggregated, owner_id
        FROM ticks_stage
        ON CONFLICT (asset_id, exchange_trade_id, time) WHERE exchange_trade_id IS NOT NULL
        DO NOTHING;
        """
    )
    inserted = cursor.rowcount
    cursor.close()
    return int(inserted or 0)
