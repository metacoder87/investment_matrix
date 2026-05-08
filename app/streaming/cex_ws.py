from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any

import requests

from app.streaming.base_ws import BaseTradeStreamer
from app.streaming.publisher import RedisPublisher
from app.streaming.symbols import CanonicalSymbol, parse_symbol


def _to_symbol_key(value: str | CanonicalSymbol) -> str:
    if isinstance(value, CanonicalSymbol):
        return value.dash().upper()
    return str(value or "").strip().upper().replace("/", "-")


def _split_symbol(value: str | CanonicalSymbol, *, usd_to_usdt: bool = True) -> tuple[str, str]:
    symbol = _to_symbol_key(value)
    parsed = parse_symbol(symbol)
    quote = parsed.quote
    if usd_to_usdt and quote == "USD":
        quote = "USDT"
    return parsed.base, quote


def _ts_seconds(value: Any, *, default: float | None = None) -> float:
    if value in (None, ""):
        return default if default is not None else time.time()
    numeric = float(value)
    if numeric > 1e17:
        return numeric / 1_000_000_000
    if numeric > 1e14:
        return numeric / 1_000_000
    if numeric > 1e11:
        return numeric / 1_000
    return numeric


def _parse_iso(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class OKXTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="OKX", url="wss://ws.okx.com:8443/ws/v5/public")
        self._inst_to_symbol: dict[str, str] = {}
        self._inst_ids: list[str] = []
        for symbol in symbols:
            inst_id = self._to_inst_id(symbol)
            self._inst_ids.append(inst_id)

    def _to_inst_id(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol)
        inst_id = f"{base}-{quote}"
        self._inst_to_symbol[inst_id] = inst_id
        return inst_id

    def get_subscription_message(self) -> dict:
        args = []
        for inst_id in self._inst_ids:
            args.append({"channel": "trades", "instId": inst_id})
            args.append({"channel": "tickers", "instId": inst_id})
        return {"op": "subscribe", "args": args}

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        arg = msg.get("arg") if isinstance(msg, dict) else None
        if not isinstance(arg, dict):
            return
        channel = str(arg.get("channel") or "")
        data = msg.get("data") or []
        if channel == "trades":
            recv_ts = time.time()
            for item in data:
                inst_id = str(item.get("instId") or arg.get("instId") or "").upper()
                await publisher.publish_trade(
                    exchange="okx",
                    symbol=self._inst_to_symbol.get(inst_id, inst_id),
                    ts=_ts_seconds(item.get("ts"), default=recv_ts),
                    recv_ts=recv_ts,
                    price=float(item.get("px") or 0.0),
                    amount=float(item.get("sz") or 0.0),
                    side=str(item.get("side") or "").lower() or None,
                    trade_id=str(item.get("tradeId")) if item.get("tradeId") is not None else None,
                )
        elif channel == "tickers":
            recv_ts = time.time()
            for item in data:
                inst_id = str(item.get("instId") or arg.get("instId") or "").upper()
                await publisher.publish_quote(
                    exchange="okx",
                    symbol=self._inst_to_symbol.get(inst_id, inst_id),
                    ts=_ts_seconds(item.get("ts"), default=recv_ts),
                    recv_ts=recv_ts,
                    bid=_float_or_none(item.get("bidPx")),
                    ask=_float_or_none(item.get("askPx")),
                    bid_size=_float_or_none(item.get("bidSz")),
                    ask_size=_float_or_none(item.get("askSz")),
                )

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        inst_ids = [self._to_inst_id(symbol) for symbol in symbols]
        self._inst_ids = sorted(set(self._inst_ids + inst_ids))
        args = []
        for inst_id in inst_ids:
            args.append({"channel": "trades", "instId": inst_id})
            args.append({"channel": "tickers", "instId": inst_id})
        return {"op": "subscribe", "args": args} if args else None

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        inst_ids = [self._to_inst_id(symbol) for symbol in symbols]
        self._inst_ids = [inst_id for inst_id in self._inst_ids if inst_id not in inst_ids]
        args = []
        for inst_id in inst_ids:
            args.append({"channel": "trades", "instId": inst_id})
            args.append({"channel": "tickers", "instId": inst_id})
        return {"op": "unsubscribe", "args": args} if args else None


class BybitTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="Bybit", url="wss://stream.bybit.com/v5/public/spot")
        self._market_to_symbol: dict[str, str] = {}
        self._market_ids: list[str] = []
        for symbol in symbols:
            self._market_ids.append(self._to_market_id(symbol))

    def _to_market_id(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol)
        market_id = f"{base}{quote}"
        self._market_to_symbol[market_id] = f"{base}-{quote}"
        return market_id

    def get_subscription_message(self) -> dict:
        args = []
        for market_id in self._market_ids:
            args.append(f"publicTrade.{market_id}")
            args.append(f"tickers.{market_id}")
        return {"op": "subscribe", "args": args}

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        topic = str(msg.get("topic") or "")
        data = msg.get("data") or []
        recv_ts = time.time()
        if topic.startswith("publicTrade."):
            for item in data:
                market_id = str(item.get("s") or topic.split(".", 1)[1]).upper()
                await publisher.publish_trade(
                    exchange="bybit",
                    symbol=self._market_to_symbol.get(market_id, market_id),
                    ts=_ts_seconds(item.get("T"), default=recv_ts),
                    recv_ts=recv_ts,
                    price=float(item.get("p") or 0.0),
                    amount=float(item.get("v") or 0.0),
                    side=str(item.get("S") or "").lower() or None,
                    trade_id=str(item.get("i")) if item.get("i") is not None else None,
                )
        elif topic.startswith("tickers."):
            item = data if isinstance(data, dict) else data[0] if data else {}
            market_id = str(item.get("symbol") or topic.split(".", 1)[1]).upper()
            await publisher.publish_quote(
                exchange="bybit",
                symbol=self._market_to_symbol.get(market_id, market_id),
                ts=_ts_seconds(msg.get("ts") or item.get("ts"), default=recv_ts),
                recv_ts=recv_ts,
                bid=_float_or_none(item.get("bid1Price")),
                ask=_float_or_none(item.get("ask1Price")),
                bid_size=_float_or_none(item.get("bid1Size")),
                ask_size=_float_or_none(item.get("ask1Size")),
            )

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        market_ids = [self._to_market_id(symbol) for symbol in symbols]
        self._market_ids = sorted(set(self._market_ids + market_ids))
        args = [topic for market_id in market_ids for topic in (f"publicTrade.{market_id}", f"tickers.{market_id}")]
        return {"op": "subscribe", "args": args} if args else None

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        market_ids = [self._to_market_id(symbol) for symbol in symbols]
        self._market_ids = [market_id for market_id in self._market_ids if market_id not in market_ids]
        args = [topic for market_id in market_ids for topic in (f"publicTrade.{market_id}", f"tickers.{market_id}")]
        return {"op": "unsubscribe", "args": args} if args else None


class GateTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="Gateio", url="wss://api.gateio.ws/ws/v4/")
        self._pair_to_symbol: dict[str, str] = {}
        self._pairs: list[str] = []
        for symbol in symbols:
            self._pairs.append(self._to_pair(symbol))

    def _to_pair(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol)
        pair = f"{base}_{quote}"
        self._pair_to_symbol[pair] = f"{base}-{quote}"
        return pair

    def get_subscription_message(self) -> dict:
        return {"time": int(time.time()), "channel": "spot.trades", "event": "subscribe", "payload": self._pairs}

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if msg.get("channel") != "spot.trades" or msg.get("event") != "update":
            return
        result = msg.get("result") or []
        items = result if isinstance(result, list) else [result]
        recv_ts = time.time()
        for item in items:
            pair = str(item.get("currency_pair") or "").upper()
            await publisher.publish_trade(
                exchange="gateio",
                symbol=self._pair_to_symbol.get(pair, pair.replace("_", "-")),
                ts=_ts_seconds(item.get("create_time_ms") or item.get("create_time"), default=recv_ts),
                recv_ts=recv_ts,
                price=float(item.get("price") or 0.0),
                amount=float(item.get("amount") or 0.0),
                side=str(item.get("side") or "").lower() or None,
                trade_id=str(item.get("id")) if item.get("id") is not None else None,
            )

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        pairs = [self._to_pair(symbol) for symbol in symbols]
        self._pairs = sorted(set(self._pairs + pairs))
        return {"time": int(time.time()), "channel": "spot.trades", "event": "subscribe", "payload": pairs} if pairs else None

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        pairs = [self._to_pair(symbol) for symbol in symbols]
        self._pairs = [pair for pair in self._pairs if pair not in pairs]
        return {"time": int(time.time()), "channel": "spot.trades", "event": "unsubscribe", "payload": pairs} if pairs else None


class KuCoinTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="KuCoin", url="wss://ws-api-spot.kucoin.com/")
        self._symbols = [self._to_market_id(symbol) for symbol in symbols]

    def _to_market_id(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol)
        return f"{base}-{quote}"

    async def run_forever(self, publisher: RedisPublisher) -> None:
        while True:
            try:
                data = await asyncio.to_thread(self._fetch_public_token)
                endpoint = data["instanceServers"][0]["endpoint"]
                token = data["token"]
                self.url = f"{endpoint}?token={token}&connectId={uuid.uuid4().hex}"
                await super().run_forever(publisher)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.exception("KuCoin bootstrap failed: %s; retrying in 30s", exc)
                await asyncio.sleep(30)

    def _fetch_public_token(self) -> dict:
        response = requests.post("https://api.kucoin.com/api/v1/bullet-public", timeout=10)
        response.raise_for_status()
        payload = response.json()
        return payload["data"]

    def get_subscription_message(self) -> dict:
        return {
            "id": str(int(time.time() * 1000)),
            "type": "subscribe",
            "topic": f"/market/match:{','.join(self._symbols)}",
            "privateChannel": False,
            "response": True,
        }

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if msg.get("type") != "message" or "match" not in str(msg.get("topic") or ""):
            return
        data = msg.get("data") or {}
        recv_ts = time.time()
        symbol = str(data.get("symbol") or "").upper()
        await publisher.publish_trade(
            exchange="kucoin",
            symbol=symbol,
            ts=_ts_seconds(data.get("time"), default=recv_ts),
            recv_ts=recv_ts,
            price=float(data.get("price") or 0.0),
            amount=float(data.get("size") or 0.0),
            side=str(data.get("side") or "").lower() or None,
            trade_id=str(data.get("tradeId")) if data.get("tradeId") is not None else None,
        )

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        market_ids = [self._to_market_id(symbol) for symbol in symbols]
        self._symbols = sorted(set(self._symbols + market_ids))
        return {
            "id": str(int(time.time() * 1000)),
            "type": "subscribe",
            "topic": f"/market/match:{','.join(market_ids)}",
            "privateChannel": False,
            "response": True,
        } if market_ids else None

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        market_ids = [self._to_market_id(symbol) for symbol in symbols]
        self._symbols = [symbol for symbol in self._symbols if symbol not in market_ids]
        return {
            "id": str(int(time.time() * 1000)),
            "type": "unsubscribe",
            "topic": f"/market/match:{','.join(market_ids)}",
            "privateChannel": False,
            "response": True,
        } if market_ids else None


class BitfinexTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="Bitfinex", url="wss://api-pub.bitfinex.com/ws/2")
        self._symbol_to_exchange_symbol: dict[str, str] = {}
        self._chan_to_symbol: dict[int, str] = {}
        self._symbol_to_chan: dict[str, int] = {}
        self._exchange_symbols = [self._to_exchange_symbol(symbol) for symbol in symbols]

    def _to_exchange_symbol(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol, usd_to_usdt=False)
        exchange_symbol = f"t{base}{quote}"
        self._symbol_to_exchange_symbol[exchange_symbol] = f"{base}-{quote}"
        return exchange_symbol

    def get_subscription_message(self) -> list[dict]:
        return [{"event": "subscribe", "channel": "trades", "symbol": symbol} for symbol in self._exchange_symbols]

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if isinstance(msg, dict):
            if msg.get("event") == "subscribed" and msg.get("channel") == "trades":
                chan_id = int(msg.get("chanId"))
                symbol = str(msg.get("symbol") or "")
                self._chan_to_symbol[chan_id] = self._symbol_to_exchange_symbol.get(symbol, symbol)
                self._symbol_to_chan[symbol] = chan_id
            return
        if not (isinstance(msg, list) and len(msg) >= 3 and msg[1] in {"te", "tu"}):
            return
        chan_id = int(msg[0])
        trade = msg[2]
        if not isinstance(trade, list) or len(trade) < 4:
            return
        amount = float(trade[2] or 0.0)
        await publisher.publish_trade(
            exchange="bitfinex",
            symbol=self._chan_to_symbol.get(chan_id, "UNKNOWN"),
            ts=_ts_seconds(trade[1], default=time.time()),
            recv_ts=time.time(),
            price=float(trade[3] or 0.0),
            amount=abs(amount),
            side="buy" if amount > 0 else "sell",
            trade_id=str(trade[0]) if trade[0] is not None else None,
        )

    def _make_subscription_payload(self, symbols: list[str]) -> list[dict] | None:
        exchange_symbols = [self._to_exchange_symbol(symbol) for symbol in symbols]
        self._exchange_symbols = sorted(set(self._exchange_symbols + exchange_symbols))
        return [{"event": "subscribe", "channel": "trades", "symbol": symbol} for symbol in exchange_symbols]

    def _make_unsubscription_payload(self, symbols: list[str]) -> list[dict] | None:
        payloads = []
        for symbol in symbols:
            exchange_symbol = self._to_exchange_symbol(symbol)
            chan_id = self._symbol_to_chan.get(exchange_symbol)
            if chan_id is not None:
                payloads.append({"event": "unsubscribe", "chanId": chan_id})
            if exchange_symbol in self._exchange_symbols:
                self._exchange_symbols.remove(exchange_symbol)
        return payloads or None


class CryptoComTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="CryptoCom", url="wss://stream.crypto.com/exchange/v1/market")
        self._inst_to_symbol: dict[str, str] = {}
        self._instrument_names = [self._to_instrument(symbol) for symbol in symbols]

    def _to_instrument(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol)
        instrument = f"{base}_{quote}"
        self._inst_to_symbol[instrument] = f"{base}-{quote}"
        return instrument

    def get_subscription_message(self) -> dict:
        channels = [channel for inst in self._instrument_names for channel in (f"trade.{inst}", f"ticker.{inst}")]
        return {"id": 1, "method": "subscribe", "params": {"channels": channels}, "nonce": int(time.time() * 1000)}

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        result = msg.get("result") if isinstance(msg, dict) else None
        if not isinstance(result, dict):
            return
        channel = str(result.get("channel") or "")
        data = result.get("data") or []
        recv_ts = time.time()
        if channel.startswith("trade."):
            inst = channel.split(".", 1)[1]
            for item in data:
                await publisher.publish_trade(
                    exchange="cryptocom",
                    symbol=self._inst_to_symbol.get(inst, inst.replace("_", "-")),
                    ts=_ts_seconds(item.get("t"), default=recv_ts),
                    recv_ts=recv_ts,
                    price=float(item.get("p") or 0.0),
                    amount=float(item.get("q") or item.get("s") or 0.0),
                    side=str(item.get("side") or item.get("S") or "").lower() or None,
                    trade_id=str(item.get("d")) if item.get("d") is not None else None,
                )
        elif channel.startswith("ticker."):
            inst = channel.split(".", 1)[1]
            item = data[0] if data else {}
            await publisher.publish_quote(
                exchange="cryptocom",
                symbol=self._inst_to_symbol.get(inst, inst.replace("_", "-")),
                ts=_ts_seconds(item.get("t"), default=recv_ts),
                recv_ts=recv_ts,
                bid=_float_or_none(item.get("b")),
                ask=_float_or_none(item.get("a")),
                bid_size=_float_or_none(item.get("bs")),
                ask_size=_float_or_none(item.get("ks") or item.get("as")),
            )

    def _make_subscription_payload(self, symbols: list[str]) -> dict | None:
        instruments = [self._to_instrument(symbol) for symbol in symbols]
        self._instrument_names = sorted(set(self._instrument_names + instruments))
        channels = [channel for inst in instruments for channel in (f"trade.{inst}", f"ticker.{inst}")]
        return {"id": int(time.time() * 1000), "method": "subscribe", "params": {"channels": channels}} if channels else None

    def _make_unsubscription_payload(self, symbols: list[str]) -> dict | None:
        instruments = [self._to_instrument(symbol) for symbol in symbols]
        self._instrument_names = [inst for inst in self._instrument_names if inst not in instruments]
        channels = [channel for inst in instruments for channel in (f"trade.{inst}", f"ticker.{inst}")]
        return {"id": int(time.time() * 1000), "method": "unsubscribe", "params": {"channels": channels}} if channels else None


class GeminiTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        first_symbol = symbols[0] if symbols else CanonicalSymbol("BTC", "USD")
        market_id = self._to_market_id(first_symbol)
        super().__init__([first_symbol], name="Gemini", url=f"wss://api.gemini.com/v1/marketdata/{market_id}")
        self._market_to_symbol = {market_id: _to_symbol_key(first_symbol)}

    def _to_market_id(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol, usd_to_usdt=False)
        return f"{base}{quote}".lower()

    def get_subscription_message(self) -> dict:
        return {"type": "subscribe", "subscriptions": [{"name": "trades"}]}

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        recv_ts = time.time()
        events = msg.get("events") if isinstance(msg, dict) else None
        if isinstance(events, list):
            market_id = str(msg.get("symbol") or "").lower()
            for item in events:
                if item.get("type") != "trade":
                    continue
                await publisher.publish_trade(
                    exchange="gemini",
                    symbol=self._market_to_symbol.get(market_id, market_id.upper()),
                    ts=_ts_seconds(item.get("timestampms") or msg.get("timestampms"), default=recv_ts),
                    recv_ts=recv_ts,
                    price=float(item.get("price") or 0.0),
                    amount=float(item.get("amount") or 0.0),
                    side=str(item.get("makerSide") or item.get("side") or "").lower() or None,
                    trade_id=str(item.get("tid")) if item.get("tid") is not None else None,
                )


class BitstampTradeStreamer(BaseTradeStreamer):
    def __init__(self, symbols: list[CanonicalSymbol]) -> None:
        super().__init__(symbols, name="Bitstamp", url="wss://ws.bitstamp.net")
        self._channel_to_symbol: dict[str, str] = {}
        self._channels = [self._to_channel(symbol) for symbol in symbols]

    def _to_channel(self, symbol: str | CanonicalSymbol) -> str:
        base, quote = _split_symbol(symbol, usd_to_usdt=False)
        channel = f"live_trades_{base.lower()}{quote.lower()}"
        self._channel_to_symbol[channel] = f"{base}-{quote}"
        return channel

    def get_subscription_message(self) -> list[dict]:
        return [{"event": "bts:subscribe", "data": {"channel": channel}} for channel in self._channels]

    async def process_message(self, msg: Any, publisher: RedisPublisher) -> None:
        if msg.get("event") != "trade":
            return
        channel = str(msg.get("channel") or "")
        data = msg.get("data") or {}
        recv_ts = time.time()
        side_value = data.get("type")
        side = "buy" if str(side_value) == "0" else "sell" if str(side_value) == "1" else None
        await publisher.publish_trade(
            exchange="bitstamp",
            symbol=self._channel_to_symbol.get(channel, channel.removeprefix("live_trades_").upper()),
            ts=_ts_seconds(data.get("microtimestamp") or data.get("timestamp"), default=recv_ts),
            recv_ts=recv_ts,
            price=float(data.get("price") or 0.0),
            amount=float(data.get("amount") or 0.0),
            side=side,
            trade_id=str(data.get("id")) if data.get("id") is not None else None,
        )

    def _make_subscription_payload(self, symbols: list[str]) -> list[dict] | None:
        channels = [self._to_channel(symbol) for symbol in symbols]
        self._channels = sorted(set(self._channels + channels))
        return [{"event": "bts:subscribe", "data": {"channel": channel}} for channel in channels]

    def _make_unsubscription_payload(self, symbols: list[str]) -> list[dict] | None:
        channels = [self._to_channel(symbol) for symbol in symbols]
        self._channels = [channel for channel in self._channels if channel not in channels]
        return [{"event": "bts:unsubscribe", "data": {"channel": channel}} for channel in channels]


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
