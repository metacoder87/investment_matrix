from __future__ import annotations

import asyncio
import json
import logging

from app.config import settings
from app.redis_client import RedisClient
from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.binance_ws import BinanceTradeStreamer
from app.streaming.cex_ws import (
    BitfinexTradeStreamer,
    BitstampTradeStreamer,
    BybitTradeStreamer,
    CryptoComTradeStreamer,
    GateTradeStreamer,
    GeminiTradeStreamer,
    KuCoinTradeStreamer,
    OKXTradeStreamer,
)
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
                symbols = _command_symbols(data)
                exchange = data.get("exchange", "COINBASE").upper()
                
                streamer = streamers.get(exchange)
                if streamer and symbols:
                    logger.info(f"Received dynamic subscription for {symbols} on {exchange}")
                    await streamer.subscribe(symbols)
                else:
                    logger.warning(f"No streamer found for exchange {exchange} or invalid symbols {symbols}")
            elif action == "unsubscribe":
                symbols = _command_symbols(data)
                exchange = data.get("exchange", "COINBASE").upper()
                streamer = streamers.get(exchange)
                if streamer and symbols:
                    logger.info(f"Received dynamic unsubscription for {symbols} on {exchange}")
                    await streamer.unsubscribe(symbols)
            elif action == "replace_set":
                symbols = _command_symbols(data)
                exchange = data.get("exchange", "COINBASE").upper()
                streamer = streamers.get(exchange)
                if streamer:
                    logger.info("Received dynamic replacement set for %s: %s symbols", exchange, len(symbols))
                    await streamer.replace_set(symbols)
                    
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
        elif exchange == "OKX":
            streamer = OKXTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["OKX"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "BYBIT":
            streamer = BybitTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["BYBIT"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "KUCOIN":
            streamer = KuCoinTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["KUCOIN"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "GATEIO":
            streamer = GateTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["GATEIO"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "BITFINEX":
            streamer = BitfinexTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["BITFINEX"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "CRYPTOCOM":
            streamer = CryptoComTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["CRYPTOCOM"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "GEMINI":
            streamer = GeminiTradeStreamer(symbols[:1])
            streamers["GEMINI"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
        elif exchange == "BITSTAMP":
            streamer = BitstampTradeStreamer(symbols[: settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE])
            streamers["BITSTAMP"] = streamer
            tasks.append(asyncio.create_task(streamer.run_forever(publisher)))
            
        else:
            raise SystemExit(
                f"Unsupported STREAM_EXCHANGE: {exchange!r} "
                "(supported: COINBASE,BINANCE,KRAKEN,OKX,BYBIT,KUCOIN,GATEIO,BITFINEX,CRYPTOCOM,GEMINI,BITSTAMP)"
            )

    logger.info("Streamer started: exchanges=%s symbols=%s", ",".join(exchanges), ",".join([s.dash() for s in symbols]))
    
    # Add command listener
    tasks.append(asyncio.create_task(_command_listener(redis, streamers)))
    
    await asyncio.gather(*tasks)


def main():
    asyncio.run(run_all())


def _command_symbols(data: dict) -> list[str]:
    if isinstance(data.get("symbols"), list):
        return [str(symbol).strip().upper().replace("/", "-") for symbol in data["symbols"] if str(symbol).strip()]
    symbol = data.get("symbol")
    if symbol:
        return [str(symbol).strip().upper().replace("/", "-")]
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
