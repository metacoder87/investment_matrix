from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.publisher import RedisPublisher


COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"


def _parse_iso8601(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class CoinbaseTradeStreamer(BaseTradeStreamer):
    # Note: legacy code passed string symbols directly (product_ids).
    # New architecture passes CanonicalSymbol. We adapt for backwards compatibility
    
    def __init__(self, symbols: list[str]) -> None:
        # Base class expects symbols for logging mostly. We pass them up.
        super().__init__(symbols, name="Coinbase", url=COINBASE_WS_URL) 
        self._product_ids = symbols

    def get_subscription_message(self) -> dict:
        return {
            "type": "subscribe",
            "product_ids": self._product_ids,
            "channels": ["matches"],
        }

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if msg.get("type") != "match":
            return

        recv_ts = time.time()
        ts = _parse_iso8601(str(msg.get("time") or "")) or recv_ts
        
        await publisher.publish_trade(
            exchange="coinbase",
            symbol=str(msg.get("product_id") or "UNKNOWN"),
            ts=ts,
            recv_ts=recv_ts,
            price=float(msg.get("price") or 0.0),
            amount=float(msg.get("size") or 0.0),
            side=str(msg.get("side") or "").lower() or None,
            trade_id=str(msg.get("trade_id")) if msg.get("trade_id") is not None else None,
        )

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        for symbol in symbols:
            if symbol not in self._product_ids:
                self._product_ids.append(symbol)
        return {
            "type": "subscribe",
            "product_ids": symbols,
            "channels": ["matches"],
        }

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        for symbol in symbols:
            if symbol in self._product_ids:
                self._product_ids.remove(symbol)
        return {
            "type": "unsubscribe",
            "product_ids": symbols,
            "channels": ["matches"],
        }
