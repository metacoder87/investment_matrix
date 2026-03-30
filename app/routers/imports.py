from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from celery_app import celery_app


router = APIRouter(prefix="/imports", tags=["Imports"])


@router.post("/binance-vision", status_code=202)
def import_binance_vision(
    symbol: str = Query(..., description="Symbol in BASE-QUOTE or BASE/QUOTE form."),
    exchange: str = Query(default="binance", description="Exchange label to store with assets."),
    kind: str = Query(default="trades", description="trades or aggTrades"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    owner_id: str | None = Query(default=None, description="User-scoped import; null for global."),
):
    raw_kind = kind.strip()
    if raw_kind.lower() in {"agg_trades", "aggtrades"}:
        kind = "aggTrades"
    elif raw_kind.lower() == "trades":
        kind = "trades"
    else:
        raise HTTPException(status_code=400, detail="kind must be 'trades' or 'aggTrades'")

    task = celery_app.send_task(
        "celery_worker.tasks.import_binance_vision_range",
        kwargs={
            "symbol": symbol,
            "exchange": exchange,
            "kind": kind,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "owner_id": owner_id,
        },
    )
    return {"message": "Import queued", "task_id": task.id}


@router.post("/dukascopy", status_code=202)
def import_dukascopy(
    symbol: str = Query(..., description="Symbol in BASE-QUOTE, BASE/QUOTE, or raw (e.g. BTC-USD, BTCUSD)."),
    exchange: str = Query(default="dukascopy", description="Exchange label to store with assets."),
    start_datetime: datetime = Query(..., description="Start datetime (ISO 8601)."),
    end_datetime: datetime = Query(..., description="End datetime (ISO 8601)."),
    owner_id: str | None = Query(default=None, description="User-scoped import; null for global."),
    price_scale: int = Query(default=100_000, ge=1),
    volume_scale: int = Query(default=100_000, ge=1),
):
    if start_datetime > end_datetime:
        raise HTTPException(status_code=400, detail="start_datetime must be <= end_datetime")

    task = celery_app.send_task(
        "celery_worker.tasks.import_dukascopy_range",
        kwargs={
            "symbol": symbol,
            "exchange": exchange,
            "start_datetime": start_datetime.isoformat(),
            "end_datetime": end_datetime.isoformat(),
            "owner_id": owner_id,
            "price_scale": price_scale,
            "volume_scale": volume_scale,
        },
    )
    return {"message": "Import queued", "task_id": task.id}
