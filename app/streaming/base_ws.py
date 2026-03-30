from __future__ import annotations

import asyncio
import json
import logging
import time
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
                    sub_msg = self.get_subscription_message()
                    await ws.send(json.dumps(sub_msg, separators=(",", ":")))
                    self.logger.info(f"Subscribed to initial symbols")

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
                payload = self._make_subscription_payload(msg["symbols"])
                if payload:
                    await ws.send(json.dumps(payload))
                    self.logger.info(f"Dynamically subscribed to {msg['symbols']}")

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        """Override this in subclasses to format dynamic subscription."""
        # Default behavior: generic
        return None
