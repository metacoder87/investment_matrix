from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol


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
    # or updated loop usage. Assuming `app.streamer.run_all` passes list[str] currently,
    # we need to be careful.
    # Looking at `app.streamer.py`, it does: `tasks.append(... CoinbaseTradeStreamer(product_ids) ...)` 
    # where product_ids is a list[str].
    # HOWEVER, BaseTradeStreamer expects list[CanonicalSymbol].
    # Let's override __init__ to accept list[str] like before strictly for Coinbase 
    # OR we need to update `streamer.py` to pass objects.
    # The clean "Quant" way is to fix the caller. 
    # But since `BaseTradeStreamer` takes `symbols`, let's just accept `symbols` here which
    # are strs for Coinbase in current usage, and treat them as "symbols".
    # Wait, the prompt says "Refactor... to inherit". 
    # Let's make it accept list[str] cleanly by just ignoring the type hint from base if needed, 
    # or better: we update `streamer.py` later.
    # For now, let's keep __init__ signature compatible with `streamer.py`.
    
    def __init__(self, symbols: list[str]) -> None:
        # Base class expects symbols for logging mostly. We pass them up.
        # We dummy up a list for the Base class to not crash if it iterates, 
        # but Base only uses them for len() logging.
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
        )


