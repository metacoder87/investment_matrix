from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import websockets

from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol

logger = logging.getLogger("cryptoinsight.streaming")


class BaseTradeStreamer(ABC):
    """
    Abstract base class for WebSocket trade streamers.
    
    Handles:
    - Persistent connection loop with exponential backoff.
    - Connection parameters (URL, timeouts).
    - Standardized error logging.
    """

    def __init__(
        self,
        symbols: list[CanonicalSymbol],
        name: str,
        url: str,
        ping_interval: int = 20,
        ping_timeout: int = 20,
        max_queue: int = 4096,
    ) -> None:
        self.symbols = symbols
        self.name = name
        self.url = url
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.max_queue = max_queue
        self._active_symbols = {self._symbol_key(sym) for sym in symbols}
        self._write_queue: asyncio.Queue | None = None
        
        # Sub-logger for this exchange
        self.logger = logging.getLogger(f"cryptoinsight.streaming.{name.lower()}")

    @abstractmethod
    def get_subscription_message(self) -> dict | list:
        """Return the JSON-serializable subscription message."""
        pass

    @abstractmethod
    async def process_message(self, message: Any, publisher: RedisPublisher) -> None:
        """Parse the raw message and publish trades if present."""
        pass

    async def subscribe(self, symbols: list[str]) -> None:
        """Queue a subscription request for new symbols."""
        if not self._write_queue:
            return
        await self._write_queue.put({"type": "subscribe", "symbols": symbols})

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Queue an unsubscription request for symbols."""
        if not self._write_queue:
            return
        await self._write_queue.put({"type": "unsubscribe", "symbols": symbols})

    async def replace_set(self, symbols: list[str]) -> None:
        """Replace the active symbol set without restarting the process."""
        if not self._write_queue:
            return
        await self._write_queue.put({"type": "replace_set", "symbols": symbols})

    async def run_forever(self, publisher: RedisPublisher) -> None:
        self._write_queue = asyncio.Queue()
        backoff_seconds = 1.0
        
        while True:
            try:
                self.logger.info(f"Connecting to {self.url}...")
                async with websockets.connect(
                    self.url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    close_timeout=10,
                    max_queue=self.max_queue,
                ) as ws:
                    backoff_seconds = 1.0
                    
                    # Initial Subscription
                    await self._send_payload(ws, self.get_subscription_message())
                    self.logger.info("Subscribed to initial symbols")
                    await self._record_source_success()

                    # Run Read and Write loops concurrently
                    read_task = asyncio.create_task(self._read_loop(ws, publisher))
                    write_task = asyncio.create_task(self._write_loop(ws))
                    
                    done, pending = await asyncio.wait(
                        [read_task, write_task], 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # If one fails, cancel the other and reconnect
                    for task in pending:
                        task.cancel()
                    for task in done:
                        try:
                            task.result()
                        except Exception as e:
                            self.logger.error(f"Task failed: {e}")
                            raise e # Trigger outer reconnection

            except asyncio.CancelledError:
                self.logger.info("Stopping streamer...")
                raise
            except Exception as e:
                await self._record_source_reconnect(e)
                self.logger.exception(f"Connection lost: {e}; retrying in {backoff_seconds:.1f}s")
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2.0, 30.0)

    async def _read_loop(self, ws, publisher):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await self.process_message(msg, publisher)

    async def _write_loop(self, ws):
        while True:
            msg = await self._write_queue.get()
            if msg["type"] == "subscribe":
                symbols = self._normalize_symbols(msg["symbols"])
                payload = self._make_subscription_payload(symbols)
                if payload:
                    await self._send_payload(ws, payload)
                    self._active_symbols.update(symbols)
                    self.logger.info(f"Dynamically subscribed to {symbols}")
            elif msg["type"] == "unsubscribe":
                symbols = self._normalize_symbols(msg["symbols"])
                payload = self._make_unsubscription_payload(symbols)
                if payload:
                    await self._send_payload(ws, payload)
                    self._active_symbols.difference_update(symbols)
                    self.logger.info(f"Dynamically unsubscribed from {symbols}")
            elif msg["type"] == "replace_set":
                desired = set(self._normalize_symbols(msg["symbols"]))
                removed = sorted(self._active_symbols - desired)
                added = sorted(desired - self._active_symbols)
                if removed:
                    payload = self._make_unsubscription_payload(removed)
                    if payload:
                        await self._send_payload(ws, payload)
                if added:
                    payload = self._make_subscription_payload(added)
                    if payload:
                        await self._send_payload(ws, payload)
                self._active_symbols = desired
                self.logger.info("Replaced active symbols: added=%s removed=%s total=%s", added, removed, len(desired))

    def _make_subscription_payload(self, symbols: list[str]) -> dict | list | None:
        """Override this in subclasses to format dynamic subscription."""
        # Default behavior: generic
        return None

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | list | None:
        """Override this in subclasses to format dynamic unsubscription."""
        return None

    async def _send_payload(self, ws, payload: dict | list) -> None:
        if isinstance(payload, list):
            for item in payload:
                if item:
                    await ws.send(json.dumps(item, separators=(",", ":")))
            return
        await ws.send(json.dumps(payload, separators=(",", ":")))

    def _normalize_symbols(self, symbols: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            key = str(symbol or "").strip().upper().replace("/", "-")
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    def _symbol_key(self, symbol: Any) -> str:
        if hasattr(symbol, "dash"):
            return symbol.dash().upper()
        return str(symbol or "").strip().upper().replace("/", "-")

    async def _record_source_success(self) -> None:
        await asyncio.to_thread(self._record_source_health, None)

    async def _record_source_reconnect(self, exc: Exception) -> None:
        await asyncio.to_thread(self._record_source_health, exc)

    def _record_source_health(self, exc: Exception | None) -> None:
        try:
            from datetime import datetime, timezone

            from app.models.research import DataSourceHealth
            from database import session_scope

            source = self.name.lower()
            now = datetime.now(timezone.utc)
            with session_scope() as db:
                row = db.query(DataSourceHealth).filter(DataSourceHealth.source == source).first()
                if row is None:
                    row = DataSourceHealth(
                        source=source,
                        source_type="cex",
                        enabled=True,
                        websocket_supported=True,
                        rest_supported=True,
                    )
                    db.add(row)
                if exc is None:
                    row.last_success_at = now
                    row.last_error = None
                else:
                    row.reconnect_count = int(row.reconnect_count or 0) + 1
                    row.last_error_at = now
                    row.last_error = str(exc)
        except Exception:
            self.logger.debug("Failed to record source health", exc_info=True)
