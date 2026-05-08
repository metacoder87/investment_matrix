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
        quote_stream_key: str = "market_quotes",
        latest_ttl_seconds: int = 60 * 60,
        stream_maxlen: int = 100_000,
    ) -> None:
        self._redis = redis
        self._stream_key = stream_key
        self._quote_stream_key = quote_stream_key
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
        trade_id: str | None = None,
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
        if trade_id is not None:
            payload["trade_id"] = trade_id
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
        if trade_id is not None:
            stream_fields["trade_id"] = str(trade_id)
        await self._redis.xadd(
            self._stream_key,
            stream_fields,
            maxlen=self._stream_maxlen,
            approximate=True,
        )

    async def publish_quote(
        self,
        *,
        exchange: str,
        symbol: str,
        ts: float,
        bid: float | None,
        ask: float | None,
        bid_size: float | None = None,
        ask_size: float | None = None,
        recv_ts: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        exchange = exchange.strip().lower()
        symbol = symbol.strip().upper()
        recv_ts = float(recv_ts if recv_ts is not None else time.time())
        bid_f = float(bid) if bid is not None else None
        ask_f = float(ask) if ask is not None else None
        mid = (bid_f + ask_f) / 2 if bid_f is not None and ask_f is not None else None
        spread_bps = ((ask_f - bid_f) / mid) * 10_000 if mid and ask_f is not None and bid_f is not None else None

        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "ts": float(ts),
            "recv_ts": recv_ts,
            "bid": bid_f,
            "ask": ask_f,
            "bid_size": float(bid_size) if bid_size is not None else None,
            "ask_size": float(ask_size) if ask_size is not None else None,
            "mid": mid,
            "spread_bps": spread_bps,
        }
        if extra:
            payload["extra"] = extra

        message = json.dumps(payload, separators=(",", ":"))
        await self._redis.set(
            f"latest_quote:{exchange}:{symbol}",
            message,
            ex=self._latest_ttl_seconds,
        )
        await self._redis.publish(f"quotes:{exchange}:{symbol}", message)

        stream_fields: dict[str, str] = {
            "exchange": exchange,
            "symbol": symbol,
            "ts": str(ts),
            "recv_ts": str(recv_ts),
        }
        for key in ("bid", "ask", "bid_size", "ask_size", "mid", "spread_bps"):
            value = payload.get(key)
            if value is not None:
                stream_fields[key] = str(value)
        await self._redis.xadd(
            self._quote_stream_key,
            stream_fields,
            maxlen=self._stream_maxlen,
            approximate=True,
        )
