from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets

from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol


logger = logging.getLogger("cryptoinsight.streaming.kraken")

KRAKEN_WS_URL = "wss://ws.kraken.com"

_KRAKEN_BASE_ALIASES = {
    "BTC": "XBT",
    "DOGE": "XDG",
}
_KRAKEN_BASE_ALIASES_REV = {v: k for k, v in _KRAKEN_BASE_ALIASES.items()}


def _to_kraken_pair(sym: CanonicalSymbol) -> tuple[str, str]:
    base = _KRAKEN_BASE_ALIASES.get(sym.base, sym.base)
    quote = sym.quote
    if quote == "USDT":
        quote = "USD"
    pair = f"{base}/{quote}"
    canonical = f"{_KRAKEN_BASE_ALIASES_REV.get(base, base)}-{quote}"
    return pair, canonical


class KrakenTradeStreamer:
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        self._pairs: list[str] = []
        self._pair_to_symbol: dict[str, str] = {}
        for sym in symbols:
            pair, canonical = _to_kraken_pair(sym)
            self._pairs.append(pair)
            self._pair_to_symbol[pair] = canonical

    async def run_forever(self, publisher: RedisPublisher) -> None:
        subscribe = {"event": "subscribe", "pair": self._pairs, "subscription": {"name": "trade"}}
        backoff_seconds = 1.0
        while True:
            try:
                async with websockets.connect(
                    KRAKEN_WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_queue=4096,
                ) as ws:
                    backoff_seconds = 1.0
                    await ws.send(json.dumps(subscribe, separators=(",", ":")))
                    logger.info("Subscribed to trades: %s", ",".join(self._pairs))

                    async for raw in ws:
                        try:
                            msg: Any = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # System events are dicts.
                        if isinstance(msg, dict):
                            continue

                        # Trade messages are arrays: [channel_id, trades, "trade", pair]
                        if not (isinstance(msg, list) and len(msg) >= 4 and msg[2] == "trade"):
                            continue

                        pair = str(msg[3])
                        symbol = self._pair_to_symbol.get(pair, pair.replace("/", "-"))
                        trades = msg[1]
                        if not isinstance(trades, list):
                            continue

                        recv_ts = time.time()
                        for t in trades:
                            if not (isinstance(t, list) and len(t) >= 4):
                                continue
                            price_s, amount_s, ts_s, side_s = t[0], t[1], t[2], t[3]
                            side = "buy" if str(side_s).lower().startswith("b") else "sell"
                            await publisher.publish_trade(
                                exchange="kraken",
                                symbol=symbol,
                                ts=float(ts_s),
                                recv_ts=recv_ts,
                                price=float(price_s),
                                amount=float(amount_s),
                                side=side,
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Disconnected; retrying in %.1fs", backoff_seconds)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2.0, 30.0)

