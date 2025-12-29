from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets

from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol
from app.config import settings


logger = logging.getLogger("cryptoinsight.streaming.binance")

def get_binance_ws_url():
    tld = settings.BINANCE_TLD.lower()
    return f"wss://stream.binance.{tld}:9443/ws"


def _to_stream_symbol(sym: CanonicalSymbol) -> tuple[str, str]:
    # Binance trade stream uses e.g. "btcusdt@trade".
    base = sym.base
    quote = sym.quote
    if quote == "USD":
        quote = "USDT"
    market_id = f"{base}{quote}".lower()
    return market_id, f"{market_id}@trade"


class BinanceTradeStreamer:
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        self._symbols = symbols
        self._market_id_to_symbol: dict[str, str] = {}
        params: list[str] = []
        for sym in symbols:
            market_id, stream = _to_stream_symbol(sym)
            self._market_id_to_symbol[market_id.upper()] = f"{sym.base}-{('USDT' if sym.quote == 'USD' else sym.quote)}"
            params.append(stream)
        self._subscribe_params = params

    async def run_forever(self, publisher: RedisPublisher) -> None:
        subscribe = {
            "method": "SUBSCRIBE",
            "params": self._subscribe_params,
            "id": 1,
        }
        backoff_seconds = 1.0
        while True:
            try:
                url = get_binance_ws_url()
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_queue=4096,
                ) as ws:
                    backoff_seconds = 1.0
                    await ws.send(json.dumps(subscribe, separators=(",", ":")))
                    logger.info("Subscribed to trades: %s", ",".join(self._subscribe_params))

                    async for raw in ws:
                        try:
                            msg: dict[str, Any] = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("e") != "trade":
                            continue
                        recv_ts = time.time()
                        symbol_raw = str(msg.get("s") or "").upper()
                        symbol = self._market_id_to_symbol.get(symbol_raw, symbol_raw)

                        # Binance: m=True means buyer is the market maker => taker was seller.
                        m = bool(msg.get("m"))
                        side = "sell" if m else "buy"

                        trade_time_ms = msg.get("T") or msg.get("E") or 0
                        ts = float(trade_time_ms) / 1000.0 if trade_time_ms else recv_ts
                        await publisher.publish_trade(
                            exchange="binance",
                            symbol=symbol,
                            ts=ts,
                            recv_ts=recv_ts,
                            price=float(msg.get("p") or 0.0),
                            amount=float(msg.get("q") or 0.0),
                            side=side,
                        )
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.InvalidStatus as e:
                if e.response.status_code == 451:
                    logger.error("Binance blocked connection (HTTP 451). If you are in the US, set BINANCE_TLD=us in your .env file.")
                    # Sleep longer to avoid spamming logs
                    await asyncio.sleep(60) 
                else:
                    logger.exception("WebSocket status error: %s", e)
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2.0, 30.0)
            except Exception:
                logger.exception("Disconnected; retrying in %.1fs", backoff_seconds)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2.0, 30.0)

