from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.redis_client import RedisClient
from app.streaming.binance_ws import BinanceTradeStreamer
from app.streaming.coinbase_ws import CoinbaseTradeStreamer
from app.streaming.kraken_ws import KrakenTradeStreamer
from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import parse_symbol_list


logger = logging.getLogger("cryptoinsight.streamer")


def _enabled_stream_exchanges() -> list[str]:
    raw = settings.STREAM_EXCHANGES.strip()
    if raw:
        return [e.strip().upper() for e in raw.split(",") if e.strip()]
    return [settings.STREAM_EXCHANGE.strip().upper()]


async def run_all() -> None:
    exchanges = _enabled_stream_exchanges()
    symbols = parse_symbol_list(settings.CORE_UNIVERSE)
    if not symbols:
        raise SystemExit("CORE_UNIVERSE is empty; set it to e.g. BTC-USD,ETH-USD")

    redis = RedisClient.get_redis()
    publisher = RedisPublisher(redis)

    tasks: list[asyncio.Task] = []
    for exchange in exchanges:
        if exchange == "COINBASE":
            product_ids = [s.dash() for s in symbols][: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE]
            tasks.append(asyncio.create_task(CoinbaseTradeStreamer(product_ids).run_forever(publisher)))
        elif exchange == "BINANCE":
            tasks.append(
                asyncio.create_task(
                    BinanceTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE]).run_forever(publisher)
                )
            )
        elif exchange == "KRAKEN":
            tasks.append(
                asyncio.create_task(
                    KrakenTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE]).run_forever(publisher)
                )
            )
        else:
            raise SystemExit(f"Unsupported STREAM_EXCHANGE: {exchange!r} (supported: COINBASE,BINANCE,KRAKEN)")

    logger.info("Streamer started: exchanges=%s symbols=%s", ",".join(exchanges), ",".join([s.dash() for s in symbols]))
    await asyncio.gather(*tasks)


def main():
    asyncio.run(run_all())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
