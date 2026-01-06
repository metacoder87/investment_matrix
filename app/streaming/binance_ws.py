from __future__ import annotations

import time
from typing import Any

from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol
from app.config import settings


def get_binance_ws_url() -> str:
    tld = settings.BINANCE_TLD.lower()
    return f"wss://stream.binance.{tld}:9443/ws"


def _to_stream_symbol(sym: CanonicalSymbol) -> tuple[str, str]:
    # Binance trade stream uses e.g. "btcusdt@trade".
    base = sym.base
    quote = sym.quote
    
    # Binance Global and US use USDT mostly, but check TLD if needed in future.
    # For now, standardize USD -> USDT for binance streams.
    if quote == "USD":
        quote = "USDT"
        
    market_id = f"{base}{quote}".lower()
    return market_id, f"{market_id}@trade"


class BinanceTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        url = get_binance_ws_url()
        super().__init__(symbols, name="Binance", url=url)
        
        self._market_id_to_symbol: dict[str, str] = {}
        self._subscribe_params: list[str] = []
        
        for sym in symbols:
            market_id, stream = _to_stream_symbol(sym)
            # Map canonical symbol (BTC-USD) for standard output
            self._market_id_to_symbol[market_id.upper()] = f"{sym.base}-{('USDT' if sym.quote == 'USD' else sym.quote)}"
            self._subscribe_params.append(stream)

    def get_subscription_message(self) -> dict:
        return {
            "method": "SUBSCRIBE",
            "params": self._subscribe_params,
            "id": 1,
        }

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if msg.get("e") != "trade":
            return

        recv_ts = time.time()
        symbol_raw = str(msg.get("s") or "").upper()
        symbol = self._market_id_to_symbol.get(symbol_raw, symbol_raw)

        # Binance: m=True means buyer is the market maker => taker was seller.
        m = bool(msg.get("m"))
        side = "sell" if m else "buy"

        trade_time_ms = msg.get("T") or msg.get("E") or 0
        ts = float(trade_time_ms) / 1000.0 if trade_time_ms else recv_ts
        
        await publisher.publish_trade(
            exchange="binance",
            symbol=symbol,
            ts=ts,
            recv_ts=recv_ts,
            price=float(msg.get("p") or 0.0),
            amount=float(msg.get("q") or 0.0),
            side=side,
        )


