from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

import websockets

from app.streaming.publisher import RedisPublisher


logger = logging.getLogger("cryptoinsight.streaming.coinbase")

COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"


def _parse_iso8601(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class CoinbaseTradeStreamer:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def run_forever(self, publisher: RedisPublisher) -> None:
        subscribe = {
            "type": "subscribe",
            "product_ids": self._symbols,
            "channels": ["matches"],
        }

        backoff_seconds = 1.0
        while True:
            try:
                async with websockets.connect(
                    COINBASE_WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_queue=1024,
                ) as ws:
                    backoff_seconds = 1.0
                    await ws.send(json.dumps(subscribe, separators=(",", ":")))
                    logger.info("Subscribed to matches: %s", ",".join(self._symbols))

                    async for raw in ws:
                        try:
                            msg: dict[str, Any] = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("type") != "match":
                            continue

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
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Disconnected; retrying in %.1fs", backoff_seconds)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2.0, 30.0)

