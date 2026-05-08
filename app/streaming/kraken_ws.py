from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol, parse_symbol

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"

_KRAKEN_BASE_ALIASES = {
    "BTC": "XBT",
    "DOGE": "XDG",
}
_KRAKEN_BASE_ALIASES_REV = {v: k for k, v in _KRAKEN_BASE_ALIASES.items()}


def _to_kraken_pair(sym: CanonicalSymbol) -> tuple[str, str]:
    base = sym.base
    quote = sym.quote
    if quote == "USDT":
        quote = "USD"
    pair = f"{base}/{quote}"
    canonical = f"{base}-{quote}"
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
            "method": "subscribe",
            "params": {
                "channel": "trade",
                "symbol": self._pairs,
                "snapshot": False,
            },
        }

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if isinstance(msg, dict):
            if msg.get("channel") == "trade":
                await self._process_v2_trade(msg, publisher)
            return

        # Trade messages are arrays: [channel_id, trades, "trade", pair]
        if not (isinstance(msg, list) and len(msg) >= 4 and msg[2] == "trade"):
            return

        pair = str(msg[3])
        symbol = self._pair_to_symbol.get(pair, _kraken_pair_to_canonical(pair))
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

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        new_pairs: list[str] = []
        for raw in symbols:
            try:
                sym = parse_symbol(raw)
            except ValueError:
                continue
            pair, canonical = _to_kraken_pair(sym)
            if pair not in self._pairs:
                self._pairs.append(pair)
            self._pair_to_symbol[pair] = canonical
            new_pairs.append(pair)

        if not new_pairs:
            return None
        return {
            "method": "subscribe",
            "params": {
                "channel": "trade",
                "symbol": new_pairs,
                "snapshot": False,
            },
        }

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        old_pairs: list[str] = []
        for raw in symbols:
            try:
                sym = parse_symbol(raw)
            except ValueError:
                continue
            pair, _canonical = _to_kraken_pair(sym)
            if pair in self._pairs:
                self._pairs.remove(pair)
            self._pair_to_symbol.pop(pair, None)
            old_pairs.append(pair)

        if not old_pairs:
            return None
        return {
            "method": "unsubscribe",
            "params": {
                "channel": "trade",
                "symbol": old_pairs,
            },
        }

    async def _process_v2_trade(self, msg: dict, publisher: RedisPublisher) -> None:
        data = msg.get("data") or []
        if not isinstance(data, list):
            return
        recv_ts = time.time()
        for item in data:
            if not isinstance(item, dict):
                continue
            pair = str(item.get("symbol") or "")
            ts = _parse_kraken_v2_timestamp(item.get("timestamp")) or recv_ts
            await publisher.publish_trade(
                exchange="kraken",
                symbol=self._pair_to_symbol.get(pair, _kraken_pair_to_canonical(pair)),
                ts=ts,
                recv_ts=recv_ts,
                price=float(item.get("price") or 0.0),
                amount=float(item.get("qty") or 0.0),
                side=str(item.get("side") or "").lower() or None,
                trade_id=str(item.get("trade_id")) if item.get("trade_id") is not None else None,
            )


def _kraken_pair_to_canonical(pair: str) -> str:
    if "/" not in pair:
        return pair.replace("/", "-").upper()
    base, quote = pair.upper().split("/", 1)
    base = _KRAKEN_BASE_ALIASES_REV.get(base, base)
    return f"{base}-{quote}"


def _parse_kraken_v2_timestamp(value) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
