from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from redis.exceptions import ResponseError

from app.redis_client import RedisClient
from app.models.market import MarketTrade
from database import init_db, session_scope


logger = logging.getLogger("cryptoinsight.writer")

STREAM_KEY = "market_trades"
GROUP = "trade_writers"
CONSUMER = "writer-1"


def _to_dt(ts_seconds: str | float | None) -> datetime | None:
    if ts_seconds is None:
        return None
    return datetime.fromtimestamp(float(ts_seconds), tz=timezone.utc)


async def ensure_consumer_group(redis) -> None:
    try:
        await redis.xgroup_create(STREAM_KEY, GROUP, id="$", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def run_writer(batch_size: int = 500) -> None:
    init_db()
    redis = RedisClient.get_redis()
    await ensure_consumer_group(redis)
    logger.info("Writer started: stream=%s group=%s consumer=%s", STREAM_KEY, GROUP, CONSUMER)

    while True:
        streams = await redis.xreadgroup(
            groupname=GROUP,
            consumername=CONSUMER,
            streams={STREAM_KEY: ">"},
            count=batch_size,
            block=1000,
        )
        if not streams:
            continue

        message_ids: list[str] = []
        rows: list[MarketTrade] = []

        for _stream_name, messages in streams:
            for message_id, fields in messages:
                message_ids.append(message_id)

                try:
                    exchange = str(fields.get("exchange", "")).strip()
                    symbol = str(fields.get("symbol", "")).strip()
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
                except Exception:
                    logger.exception("Skipping bad message id=%s fields=%s", message_id, fields)

        if rows:
            with session_scope() as db:
                db.bulk_save_objects(rows)

        if message_ids:
            await redis.xack(STREAM_KEY, GROUP, *message_ids)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_writer())


if __name__ == "__main__":
    main()
