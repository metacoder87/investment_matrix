from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.research import AssetDataStatus


READY_CANDLE_COUNT = 50
STALE_SECONDS = 15 * 60

STABLECOIN_SYMBOLS = {
    "USDT",
    "USDC",
    "DAI",
    "USDS",
    "USDE",
    "PYUSD",
    "USDD",
    "USDF",
    "USDG",
    "USD1",
    "FRAX",
    "TUSD",
    "GUSD",
    "LUSD",
    "FDUSD",
    "RLUSD",
}

NON_ANALYZABLE_NAME_HINTS = (
    "staked ",
    "wrapped ",
    "liquidity fund",
    "treasury",
    "heloc",
    "financing",
    "xstock",
    "usd institutional",
    "stablecoin",
)


@dataclass(frozen=True)
class AssetClassification:
    is_analyzable: bool
    status: str
    reason: str | None = None


def base_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().upper().replace("/", "-")
    if "-" in raw:
        return raw.split("-", 1)[0]
    return raw


def classify_asset(symbol: str, name: str | None = None) -> AssetClassification:
    base = base_symbol(symbol)
    normalized_name = (name or "").strip().lower()

    if base in STABLECOIN_SYMBOLS:
        return AssetClassification(False, "not_applicable", "Stablecoin signals are disabled by default.")

    if any(hint in normalized_name for hint in NON_ANALYZABLE_NAME_HINTS):
        return AssetClassification(False, "not_applicable", "Asset type is not suitable for default technical signals.")

    if "_" in base or len(base) > 12:
        return AssetClassification(False, "not_applicable", "Symbol is not a standard spot-market ticker.")

    return AssetClassification(True, "unknown", None)


def update_asset_status(
    db: Session,
    *,
    exchange: str,
    symbol: str,
    status: str,
    is_supported: bool | None = None,
    is_analyzable: bool | None = None,
    row_count: int | None = None,
    latest_candle_at: datetime | None = None,
    task_id: str | None = None,
    failure_reason: str | None = None,
    metadata: dict | None = None,
) -> AssetDataStatus:
    exchange_key = exchange.strip().lower()
    symbol_key = symbol.strip().upper().replace("/", "-")
    record = (
        db.query(AssetDataStatus)
        .filter(AssetDataStatus.exchange == exchange_key, AssetDataStatus.symbol == symbol_key)
        .first()
    )
    if record is None:
        record = AssetDataStatus(
            exchange=exchange_key,
            symbol=symbol_key,
            base_symbol=base_symbol(symbol_key),
        )
        db.add(record)

    now = datetime.now(timezone.utc)
    record.status = status
    if is_supported is not None:
        record.is_supported = is_supported
    if is_analyzable is not None:
        record.is_analyzable = is_analyzable
    if row_count is not None:
        record.row_count = row_count
    if latest_candle_at is not None:
        record.latest_candle_at = latest_candle_at
    if task_id is not None:
        record.last_backfill_task_id = task_id
    if failure_reason is not None:
        record.last_failure_reason = failure_reason[:2000]
    if metadata is not None:
        record.metadata_json = metadata

    if status == "backfill_pending":
        record.last_backfill_started_at = now
    elif status in {"ready", "warming_up", "stale"}:
        record.last_backfill_completed_at = now
        record.last_failure_reason = None
    elif status in {"unsupported", "backfill_failed"}:
        record.last_backfill_failed_at = now

    return record


def build_signal_status(
    *,
    exchange: str,
    symbol: str,
    name: str | None = None,
    row_count: int = 0,
    latest_candle_at: datetime | None = None,
    status_record: AssetDataStatus | None = None,
    has_signal: bool = False,
) -> dict:
    classification = classify_asset(symbol, name)
    if not classification.is_analyzable:
        return {
            "status": classification.status,
            "reason": classification.reason,
            "exchange": exchange,
            "symbol": symbol,
            "row_count": row_count,
            "latest_candle_at": latest_candle_at.isoformat() if latest_candle_at else None,
        }

    effective_row_count = max(row_count, status_record.row_count if status_record else 0)
    effective_latest_candle_at = latest_candle_at or (status_record.latest_candle_at if status_record else None)

    if status_record and status_record.status == "unsupported":
        return {
            "status": "unsupported_market",
            "reason": status_record.last_failure_reason,
            "exchange": status_record.exchange,
            "symbol": status_record.symbol,
            "row_count": effective_row_count,
            "latest_candle_at": (
                status_record.latest_candle_at.isoformat()
                if status_record.latest_candle_at
                else (latest_candle_at.isoformat() if latest_candle_at else None)
            ),
        }

    if status_record and status_record.status in {"backfill_failed", "backfill_pending"} and effective_row_count < READY_CANDLE_COUNT:
        return {
            "status": status_record.status,
            "reason": status_record.last_failure_reason,
            "exchange": status_record.exchange,
            "symbol": status_record.symbol,
            "row_count": effective_row_count,
            "latest_candle_at": (
                status_record.latest_candle_at.isoformat()
                if status_record.latest_candle_at
                else (latest_candle_at.isoformat() if latest_candle_at else None)
            ),
        }

    if has_signal and effective_row_count >= READY_CANDLE_COUNT:
        status = "ready"
        reason = None
    elif effective_row_count <= 0:
        status = "backfill_pending" if status_record and status_record.status == "backfill_pending" else "insufficient_data"
        reason = "No persisted candles for the selected exchange."
    elif effective_row_count < READY_CANDLE_COUNT:
        status = "insufficient_data"
        reason = f"Needs {READY_CANDLE_COUNT} candles; currently has {effective_row_count}."
    else:
        status = "stale" if _is_stale(effective_latest_candle_at) else "ready"
        reason = "Latest candle is stale." if status == "stale" else None

    return {
        "status": status,
        "reason": reason,
        "exchange": exchange,
        "symbol": symbol,
        "row_count": effective_row_count,
        "latest_candle_at": effective_latest_candle_at.isoformat() if effective_latest_candle_at else None,
    }


def _is_stale(latest_candle_at: datetime | None) -> bool:
    if latest_candle_at is None:
        return False
    value = latest_candle_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - value).total_seconds() > STALE_SECONDS
