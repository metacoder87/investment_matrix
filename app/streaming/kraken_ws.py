from __future__ import annotations

import time
from typing import Any

from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol

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


class KrakenTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="Kraken", url=KRAKEN_WS_URL)
        
        self._pairs: list[str] = []
        self._pair_to_symbol: dict[str, str] = {}
        
        for sym in symbols:
            pair, canonical = _to_kraken_pair(sym)
            self._pairs.append(pair)
            self._pair_to_symbol[pair] = canonical

    def get_subscription_message(self) -> dict:
        return {
            "event": "subscribe",
            "pair": self._pairs,
            "subscription": {"name": "trade"}
        }

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        # System events are dicts.
        if isinstance(msg, dict):
            return

        # Trade messages are arrays: [channel_id, trades, "trade", pair]
        if not (isinstance(msg, list) and len(msg) >= 4 and msg[2] == "trade"):
            return

        pair = str(msg[3])
        symbol = self._pair_to_symbol.get(pair, pair.replace("/", "-"))
        trades = msg[1]
        
        if not isinstance(trades, list):
            return

        recv_ts = time.time()
        for t in trades:
            if not (isinstance(t, list) and len(t) >= 4):
                continue
            
            # [price, volume, time, side, orderType, misc]
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


