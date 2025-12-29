from __future__ import annotations

import json
import time
from typing import Any


class RedisPublisher:
    def __init__(
        self,
        redis,
        *,
        stream_key: str = "market_trades",
        latest_ttl_seconds: int = 60 * 60,
        stream_maxlen: int = 100_000,
    ) -> None:
        self._redis = redis
        self._stream_key = stream_key
        self._latest_ttl_seconds = latest_ttl_seconds
        self._stream_maxlen = stream_maxlen

    async def publish_trade(
        self,
        *,
        exchange: str,
        symbol: str,
        ts: float,
        price: float,
        amount: float,
        side: str | None,
        recv_ts: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        exchange = exchange.strip().lower()
        symbol = symbol.strip().upper()
        recv_ts = float(recv_ts if recv_ts is not None else time.time())

        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "ts": float(ts),
            "recv_ts": float(recv_ts),
            "price": float(price),
            "amount": float(amount),
            "side": (side or "").lower() or None,
        }
        if extra:
            payload["extra"] = extra

        message = json.dumps(payload, separators=(",", ":"))

        # Exchange-aware hot cache (preferred).
        await self._redis.set(
            f"latest:{exchange}:{symbol}",
            message,
            ex=self._latest_ttl_seconds,
        )
        await self._redis.publish(f"ticks:{exchange}:{symbol}", message)

        # Backwards-compatible keys (single-exchange UI/API).
        await self._redis.set(
            f"latest:{symbol}",
            message,
            ex=self._latest_ttl_seconds,
        )
        await self._redis.publish(f"ticks:{symbol}", message)

        # Durable stream for DB ingestion.
        stream_fields: dict[str, str] = {
            "exchange": exchange,
            "symbol": symbol,
            "ts": str(ts),
            "recv_ts": str(recv_ts),
            "price": str(price),
            "amount": str(amount),
            "side": str((side or "").lower()),
        }
        await self._redis.xadd(
            self._stream_key,
            stream_fields,
            maxlen=self._stream_maxlen,
            approximate=True,
        )

