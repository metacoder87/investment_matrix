from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.research import DataSourceHealth
from app.services.exchange_markets import sync_exchange_markets


SOURCE_CAPABILITIES: dict[str, dict[str, Any]] = {
    "kraken": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public websocket plus CCXT REST enableRateLimit",
    },
    "coinbase": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public exchange websocket plus CCXT REST enableRateLimit",
    },
    "binance": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public spot websocket, CCXT REST, Binance Vision historical files",
    },
    "okx": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": True,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public websocket trades/tickers plus CCXT REST enableRateLimit",
    },
    "bybit": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": True,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public v5 spot websocket plus CCXT REST enableRateLimit",
    },
    "kucoin": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public token websocket bootstrap plus CCXT REST enableRateLimit",
    },
    "gateio": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public spot websocket plus CCXT REST enableRateLimit",
    },
    "bitfinex": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public websocket v2 plus CCXT REST enableRateLimit",
    },
    "cryptocom": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": True,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public exchange websocket plus CCXT REST enableRateLimit",
    },
    "gemini": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public market data websocket plus CCXT REST enableRateLimit",
    },
    "bitstamp": {
        "source_type": "cex",
        "websocket_supported": True,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": True,
        "ohlcv_supported": True,
        "rate_limit_profile": "public websocket v2 plus CCXT REST enableRateLimit",
    },
    "dexscreener": {
        "source_type": "dex",
        "websocket_supported": False,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": False,
        "ohlcv_supported": False,
        "rate_limit_profile": "free public REST, token profiles around 60 requests/min",
    },
    "geckoterminal": {
        "source_type": "dex",
        "websocket_supported": False,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": False,
        "ohlcv_supported": True,
        "rate_limit_profile": "free public REST under GeckoTerminal/CoinGecko limits",
    },
    "defillama": {
        "source_type": "dex",
        "websocket_supported": False,
        "rest_supported": True,
        "quote_supported": False,
        "recent_trades_supported": False,
        "ohlcv_supported": False,
        "rate_limit_profile": "no-auth public REST context endpoints",
    },
}

REGION_BLOCKED_PATTERNS = (
    "451",
    "restricted location",
    "eligibility",
    "403 forbidden",
    "cloudfront",
    "configured to block access from your country",
)


def configured_stream_sources() -> list[str]:
    raw = (settings.STREAM_SOURCE_PRIORITY or "").strip()
    if not raw:
        raw = "kraken,coinbase,binance"
    seen: set[str] = set()
    sources: list[str] = []
    for part in raw.split(","):
        source = part.strip().lower()
        if source and source not in seen:
            seen.add(source)
            sources.append(source)
    return sources


def ensure_source_catalog(db: Session) -> list[DataSourceHealth]:
    now = datetime.now(timezone.utc)
    rows: list[DataSourceHealth] = []
    for source, capabilities in SOURCE_CAPABILITIES.items():
        row = db.query(DataSourceHealth).filter(DataSourceHealth.source == source).first()
        if row is None:
            row = DataSourceHealth(source=source, created_at=now.replace(tzinfo=None))
            db.add(row)
        for key, value in capabilities.items():
            setattr(row, key, value)
        row.enabled = row.enabled is not False
        row.metadata_json = {**(row.metadata_json or {}), "catalog_managed": True}
        rows.append(row)
    db.flush()
    return rows


def list_data_sources(db: Session) -> list[dict[str, Any]]:
    ensure_source_catalog(db)
    rows = db.query(DataSourceHealth).order_by(DataSourceHealth.source_type.asc(), DataSourceHealth.source.asc()).all()
    return [_source_payload(row) for row in rows]


def source_unavailable_reason(row: DataSourceHealth | None) -> str | None:
    if row is None:
        return "Source health is unavailable."
    if row.enabled is False:
        return "Source is disabled by configuration."
    if not _has_current_error(row):
        return None
    message = (row.last_error or "").strip()
    if not message:
        return None
    if source_is_region_blocked(row):
        return f"Source appears region-blocked for this runtime: {_short_error(message)}"
    if row.last_success_at is None:
        return f"Source unavailable: {_short_error(message)}"
    return None


def source_is_region_blocked(row: DataSourceHealth | None) -> bool:
    if row is None or not _has_current_error(row):
        return False
    message = (row.last_error or "").lower()
    return any(pattern in message for pattern in REGION_BLOCKED_PATTERNS)


async def sync_all_exchange_markets(db: Session, sources: list[str] | None = None) -> dict[str, Any]:
    ensure_source_catalog(db)
    selected = sources or configured_stream_sources()
    results = []
    for source in selected:
        if source not in SOURCE_CAPABILITIES or SOURCE_CAPABILITIES[source]["source_type"] != "cex":
            continue
        health = db.query(DataSourceHealth).filter(DataSourceHealth.source == source).first()
        if health and health.enabled is False:
            results.append({"exchange": source, "status": "disabled"})
            continue
        try:
            result = await sync_exchange_markets(db, exchange=source)
            _mark_source_success(health, metadata={"last_market_sync": result})
            results.append(result)
        except Exception as exc:
            _mark_source_error(health, exc)
            results.append({"exchange": source, "status": "error", "error": str(exc)})
        db.flush()
        await asyncio.sleep(0)
    return {"status": "ok", "sources": len(results), "results": results}


def _mark_source_success(row: DataSourceHealth | None, *, metadata: dict[str, Any] | None = None) -> None:
    if row is None:
        return
    now = datetime.now(timezone.utc)
    row.last_success_at = now
    row.last_error = None
    row.metadata_json = {**(row.metadata_json or {}), **(metadata or {})}


def _mark_source_error(row: DataSourceHealth | None, exc: Exception) -> None:
    if row is None:
        return
    now = datetime.now(timezone.utc)
    row.last_error_at = now
    row.last_error = str(exc)


def _has_current_error(row: DataSourceHealth) -> bool:
    if not row.last_error:
        return False
    if row.last_success_at is None:
        return True
    if row.last_error_at is None:
        return False
    return row.last_error_at >= row.last_success_at


def _short_error(message: str, limit: int = 220) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _source_payload(row: DataSourceHealth) -> dict[str, Any]:
    return {
        "source": row.source,
        "source_type": row.source_type,
        "enabled": bool(row.enabled),
        "capabilities": {
            "websocket": bool(row.websocket_supported),
            "rest": bool(row.rest_supported),
            "quote": bool(row.quote_supported),
            "recent_trades": bool(row.recent_trades_supported),
            "ohlcv": bool(row.ohlcv_supported),
        },
        "rate_limit_profile": row.rate_limit_profile,
        "reconnect_count": int(row.reconnect_count or 0),
        "messages_per_second": row.messages_per_second,
        "latency_ms": row.latency_ms,
        "capacity": {
            "redis_stream_length": row.redis_stream_length,
            "redis_pending_messages": row.redis_pending_messages,
            "writer_lag_seconds": row.writer_lag_seconds,
            "writer_batch_latency_ms": row.writer_batch_latency_ms,
            "rows_per_second": row.rows_per_second,
            "db_pressure": row.db_pressure,
            "last_telemetry_at": row.last_telemetry_at.isoformat() if row.last_telemetry_at else None,
        },
        "last_event_at": row.last_event_at.isoformat() if row.last_event_at else None,
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_error_at": row.last_error_at.isoformat() if row.last_error_at else None,
        "last_error": row.last_error,
        "unavailable_reason": source_unavailable_reason(row),
        "region_blocked": source_is_region_blocked(row),
        "metadata": row.metadata_json or {},
    }
