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

    async def run_forever(self, publisher: RedisPublisher) -> None:
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
                    # Reset backoff on successful connection
                    backoff_seconds = 1.0
                    
                    # Subscribe
                    sub_msg = self.get_subscription_message()
                    await ws.send(json.dumps(sub_msg, separators=(",", ":")))
                    self.logger.info(f"Subscribed to {len(self.symbols)} symbols")

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        
                        await self.process_message(msg, publisher)

            except asyncio.CancelledError:
                self.logger.info("Stopping streamer...")
                raise
            except websockets.exceptions.InvalidStatus as e:
                # Special handling for HTTP errors (like 429 or 403)
                self.logger.error(f"WebSocket status error: {e}")
                if e.response.status_code == 429:
                    # Rate limit; back off aggressively
                    backoff_seconds = max(backoff_seconds * 2, 60.0)
                elif e.response.status_code == 451:
                    # Legal/Geofence block
                    self.logger.critical("Geoblocked (HTTP 451). Stopping reconnection loop.")
                    # Sleep forever or a very long time to prevent loop spam
                    await asyncio.sleep(3600)
                    continue
                else:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2.0, 30.0)
            except Exception as e:
                self.logger.exception(f"Connection lost: {e}; retrying in {backoff_seconds:.1f}s")
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2.0, 30.0)
