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


import json
from app.streaming.base_ws import BaseTradeStreamer

async def _command_listener(redis, streamers: dict[str, BaseTradeStreamer]):
    pubsub = redis.pubsub()
    await pubsub.subscribe("streamer:commands")
    logger.info("Listening for dynamic commands on 'streamer:commands'")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        
        try:
            data = json.loads(message["data"])
            action = data.get("action")
            
            if action == "subscribe":
                symbol = data.get("symbol")
                exchange = data.get("exchange", "COINBASE").upper()
                
                streamer = streamers.get(exchange)
                if streamer and symbol:
                    logger.info(f"Received dynamic subscription for {symbol} on {exchange}")
                    await streamer.subscribe([symbol])
                else:
                    logger.warning(f"No streamer found for exchange {exchange} or invalid symbol {symbol}")
                    
        except Exception as e:
            logger.error(f"Error processing command: {e}")

async def run_all() -> None:
    exchanges = _enabled_stream_exchanges()
    symbols = parse_symbol_list(settings.CORE_UNIVERSE)
    if not symbols:
        raise SystemExit("CORE_UNIVERSE is empty; set it to e.g. BTC-USD,ETH-USD")

    redis = RedisClient.get_redis()
    publisher = RedisPublisher(redis)

    tasks: list[asyncio.Task] = []
    streamers: dict[str, BaseTradeStreamer] = {}

    for exchange in exchanges:
        if exchange == "COINBASE":
            # Pass initial symbols
            initial_ids = [s.dash() for s in symbols][: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE]
            streamer = CoinbaseTradeStreamer(initial_ids)
            streamers["COINBASE"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
            
        elif exchange == "BINANCE":
            streamer = BinanceTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["BINANCE"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
            
        elif exchange == "KRAKEN":
            streamer = KrakenTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["KRAKEN"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
            
        else:
            raise SystemExit(f"Unsupported STREAM_EXCHANGE: {exchange!r} (supported: COINBASE,BINANCE,KRAKEN)")

    logger.info("Streamer started: exchanges=%s symbols=%s", ",".join(exchanges), ",".join([s.dash() for s in symbols]))
    
    # Add command listener
    tasks.append(asyncio.create_task(_command_listener(redis, streamers)))
    
    await asyncio.gather(*tasks)


def main():
    asyncio.run(run_all())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
