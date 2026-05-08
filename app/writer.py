from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from redis.exceptions import ResponseError

from app.redis_client import RedisClient
from app.models.market import MarketTrade
from app.models.research import DataSourceHealth, MarketQuote
from app.services.imports.storage import bulk_insert_ticks, get_or_create_asset
from app.services.imports.types import TickRecord
from database import init_db, session_scope


logger = logging.getLogger("cryptoinsight.writer")

STREAM_KEY = "market_trades"
QUOTE_STREAM_KEY = "market_quotes"
GROUP = "trade_writers"
CONSUMER = "writer-1"


def _to_dt(ts_seconds: str | float | None) -> datetime | None:
    if ts_seconds is None:
        return None
    return datetime.fromtimestamp(float(ts_seconds), tz=timezone.utc)


async def ensure_consumer_group(redis) -> None:
    for stream_key in (STREAM_KEY, QUOTE_STREAM_KEY):
        try:
            await redis.xgroup_create(stream_key, GROUP, id="$", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


async def run_writer(batch_size: int = 500) -> None:
    init_db()
    redis = RedisClient.get_redis()
    await ensure_consumer_group(redis)
    logger.info("Writer started: stream=%s group=%s consumer=%s", STREAM_KEY, GROUP, CONSUMER)

    asset_cache: dict[tuple[str, str], int] = {}

    while True:
        streams = await redis.xreadgroup(
            groupname=GROUP,
            consumername=CONSUMER,
            streams={STREAM_KEY: ">", QUOTE_STREAM_KEY: ">"},
            count=batch_size,
            block=1000,
        )
        if not streams:
            continue

        message_ids: dict[str, list[str]] = {}
        rows: list[MarketTrade] = []
        quote_rows: list[MarketQuote] = []
        tick_batches: dict[tuple[str, str], list[TickRecord]] = {}
        health_counts: dict[str, int] = {}
        latest_event: dict[str, datetime] = {}
        batch_started = datetime.now(timezone.utc)

        for stream_name, messages in streams:
            stream_name = str(stream_name)
            for message_id, fields in messages:
                message_ids.setdefault(stream_name, []).append(message_id)
                if stream_name == QUOTE_STREAM_KEY:
                    try:
                        exchange = str(fields.get("exchange", "")).strip().lower()
                        symbol = str(fields.get("symbol", "")).strip().upper()
                        ts = _to_dt(fields.get("ts"))
                        if not exchange or not symbol or ts is None:
                            continue
                        quote_rows.append(
                            MarketQuote(
                                exchange=exchange,
                                symbol=symbol,
                                timestamp=ts,
                                receipt_timestamp=_to_dt(fields.get("recv_ts")),
                                bid=_float_or_none(fields.get("bid")),
                                ask=_float_or_none(fields.get("ask")),
                                bid_size=_float_or_none(fields.get("bid_size")),
                                ask_size=_float_or_none(fields.get("ask_size")),
                                mid=_float_or_none(fields.get("mid")),
                                spread_bps=_float_or_none(fields.get("spread_bps")),
                                source="stream",
                            )
                        )
                        health_counts[exchange] = health_counts.get(exchange, 0) + 1
                        latest_event[exchange] = max(latest_event.get(exchange, ts), ts)
                    except Exception:
                        logger.exception("Skipping bad quote message id=%s fields=%s", message_id, fields)
                    continue

                try:
                    exchange = str(fields.get("exchange", "")).strip().lower()
                    symbol = str(fields.get("symbol", "")).strip().upper()
                    ts = _to_dt(fields.get("ts"))
                    if not exchange or not symbol or ts is None:
                        continue
                    rows.append(
                        MarketTrade(
                            exchange=exchange,
                            symbol=symbol,
                            timestamp=ts,
                            receipt_timestamp=_to_dt(fields.get("recv_ts")),
                            price=Decimal(str(fields.get("price", "0"))),
                            amount=Decimal(str(fields.get("amount", "0"))),
                            side=str(fields.get("side", "")) or None,
                        )
                    )
                    health_counts[exchange] = health_counts.get(exchange, 0) + 1
                    latest_event[exchange] = max(latest_event.get(exchange, ts), ts)

                    key = (exchange, symbol)
                    tick_batches.setdefault(key, []).append(
                        TickRecord(
                            time=ts,
                            price=float(fields.get("price", 0.0)),
                            volume=float(fields.get("amount", 0.0)),
                            side=str(fields.get("side", "")) or None,
                            exchange_trade_id=str(fields.get("trade_id")) if fields.get("trade_id") else None,
                            is_aggregated=False,
                        )
                    )
                except Exception:
                    logger.exception("Skipping bad message id=%s fields=%s", message_id, fields)

        if rows or quote_rows:
            with session_scope() as db:
                if rows:
                    db.bulk_save_objects(rows)
                if quote_rows:
                    db.bulk_save_objects(quote_rows)
                for key, ticks in tick_batches.items():
                    asset_id = asset_cache.get(key)
                    if asset_id is None:
                        asset = get_or_create_asset(db, symbol=key[1], exchange=key[0])
                        asset_id = asset.id
                        asset_cache[key] = asset_id
                    bulk_insert_ticks(
                        db,
                        asset_id=asset_id,
                        rows=ticks,
                        ingest_source="stream",
                    )
                _update_source_health(db, health_counts, latest_event, batch_started)

        for stream_name, ids in message_ids.items():
            if ids:
                await redis.xack(stream_name, GROUP, *ids)


def _float_or_none(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _update_source_health(db, counts: dict[str, int], latest_event: dict[str, datetime], batch_started: datetime) -> None:
    if not counts:
        return
    elapsed = max(0.001, (datetime.now(timezone.utc) - batch_started).total_seconds())
    now = datetime.now(timezone.utc)
    for source, count in counts.items():
        event_at = latest_event.get(source) or now
        row = db.query(DataSourceHealth).filter(DataSourceHealth.source == source).first()
        if row is None:
            row = DataSourceHealth(
                source=source,
                source_type="cex",
                enabled=True,
                websocket_supported=True,
                rest_supported=True,
            )
            db.add(row)
        row.last_event_at = event_at
        row.last_success_at = now
        row.messages_per_second = float(count) / elapsed
        row.rows_per_second = float(count) / elapsed
        row.writer_batch_latency_ms = elapsed * 1000.0
        row.writer_lag_seconds = max(0.0, (now - event_at).total_seconds())
        row.last_error = None


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_writer())


if __name__ == "__main__":
    main()
