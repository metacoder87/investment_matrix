from __future__ import annotations

from dataclasses import dataclass

import ccxt

from app.config import settings


QUOTE_PRIORITY: dict[str, tuple[str, ...]] = {
    "binance": ("USDT", "USDC", "USD"),
    "coinbase": ("USD", "USDC", "USDT"),
    "kraken": ("USD", "USDT", "USDC"),
}


def primary_exchange() -> str:
    value = (settings.PRIMARY_EXCHANGE or "kraken").strip().lower()
    return value or "kraken"


def _split_exchange_list(raw: str) -> list[str]:
    seen: set[str] = set()
    exchanges: list[str] = []
    for part in raw.split(","):
        exchange = part.strip().lower()
        if exchange and exchange not in seen:
            seen.add(exchange)
            exchanges.append(exchange)
    return exchanges


@dataclass(frozen=True)
class ResolvedMarket:
    exchange: str
    ccxt_symbol: str
    db_symbol: str


def configured_exchange_priority() -> list[str]:
    raw = (settings.PRICE_EXCHANGE_PRIORITY or "").strip()
    if not raw:
        raw = (settings.STREAM_EXCHANGES or settings.STREAM_EXCHANGE or "").strip()
    if not raw:
        return [primary_exchange()]
    exchanges = _split_exchange_list(raw)
    return exchanges or [primary_exchange()]


def normalize_db_symbol(symbol: str, exchange: str) -> str:
    ccxt_symbol = normalize_ccxt_symbol(symbol, exchange)
    return ccxt_symbol.replace("/", "-").upper()


def normalize_ccxt_symbol(symbol: str, exchange: str) -> str:
    raw = (symbol or "").strip().upper()
    exchange_key = exchange.strip().lower()
    if ":" in raw:
        _, raw = raw.split(":", 1)
    if "/" in raw:
        if exchange_key == "binance" and raw.endswith("/USD"):
            base = raw.split("/", 1)[0]
            return f"{base}/USDT"
        return raw
    if "-" in raw:
        base, quote = raw.split("-", 1)
        if exchange_key == "binance" and quote == "USD":
            quote = "USDT"
        return f"{base}/{quote}"

    quote = "USD"
    if exchange_key == "binance":
        quote = "USDT"
    return f"{raw}/{quote}"


def candidate_ccxt_symbols(symbol: str, exchange: str) -> list[str]:
    exchange_key = exchange.strip().lower()
    raw = (symbol or "").strip().upper()
    if ":" in raw:
        _, raw = raw.split(":", 1)

    candidates: list[str] = []
    if "/" in raw:
        candidates.append(raw)
        base = raw.split("/", 1)[0]
    elif "-" in raw:
        base, quote = raw.split("-", 1)
        candidates.append(f"{base}/{quote}")
    else:
        base = raw

    for quote in QUOTE_PRIORITY.get(exchange_key, ("USD", "USDT", "USDC")):
        pair = f"{base}/{quote}"
        if pair not in candidates:
            candidates.append(pair)

    return candidates


async def resolve_supported_market(symbol: str, exchange: str = "auto") -> ResolvedMarket | None:
    exchanges = configured_exchange_priority() if not exchange or exchange.lower() == "auto" else [exchange.lower()]
    last_error: Exception | None = None

    for exchange_key in exchanges:
        exchange_cls = getattr(ccxt, exchange_key, None)
        if exchange_cls is None:
            continue
        market_client = exchange_cls({"enableRateLimit": True})
        try:
            markets = market_client.load_markets()
            market_keys = set(markets.keys())
            for candidate in candidate_ccxt_symbols(symbol, exchange_key):
                if candidate in market_keys:
                    return ResolvedMarket(
                        exchange=exchange_key,
                        ccxt_symbol=candidate,
                        db_symbol=candidate.replace("/", "-").upper(),
                    )
        except Exception as exc:
            last_error = exc
        finally:
            try:
                market_client.close()
            except Exception:
                pass

    if last_error:
        return None
    return None


def is_unsupported_market_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "does not have market symbol" in message
        or "bad symbol" in message
        or "symbol invalid" in message
        or "market symbol" in message and "not found" in message
    )
