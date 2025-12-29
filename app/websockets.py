from __future__ import annotations

import asyncio

from app.streamer import run_all

class RealtimeDataHandler:
    """
    Backwards-compatible wrapper around `app.streamer.MarketStreamer`.
    """

    def __init__(self, symbols):
        """
        Initializes the RealtimeDataHandler.

        Args:
            symbols (list): A list of symbols to subscribe to (e.g., ['BTC-USD']).
        """
        self.symbols = symbols

    def run(self):
        """
        Starts the streamer and subscribes to the specified symbols.
        """
        # Uses environment config for exchanges; symbols argument is kept for backwards compatibility.
        asyncio.run(run_all())

if __name__ == '__main__':
    # This allows running the handler as a standalone script for testing.
    handler = RealtimeDataHandler(symbols=['BTC-USD', 'ETH-USD'])
    handler.run()
