from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.instrument import Coin, Price
from app.models.research import AssetDataStatus, ExchangeMarket


def _seed_market(
    db_session,
    *,
    symbol: str,
    base: str,
    status: str = "ready",
    rows: int = 80,
    analyzable: bool = True,
    price: float = 100.0,
):
    now = datetime.now(timezone.utc)
    db_session.add(
        ExchangeMarket(
            exchange="kraken",
            ccxt_symbol=symbol.replace("-", "/"),
            db_symbol=symbol,
            base=base,
            quote=symbol.split("-", 1)[1],
            spot=True,
            active=True,
            is_analyzable=analyzable,
            last_seen_at=now,
        )
    )
    if status != "not_loaded":
        db_session.add(
            AssetDataStatus(
                exchange="kraken",
                symbol=symbol,
                base_symbol=base,
                status=status,
                is_supported=status not in {"unsupported", "unsupported_market"},
                is_analyzable=analyzable,
                row_count=rows,
                latest_candle_at=now,
                last_failure_reason=None if status == "ready" else f"{status} reason",
            )
        )
    db_session.add(Coin(id=base.lower(), symbol=base.lower(), name=base.title(), current_price=price, market_cap=1000000))
    for idx in range(max(rows, 1)):
        value = price + idx * 0.01
        db_session.add(
            Price(
                exchange="kraken",
                symbol=symbol,
                timestamp=now - timedelta(minutes=rows - idx),
                open=value,
                high=value + 1,
                low=value - 1,
                close=value,
                volume=10,
            )
        )


def test_market_assets_endpoint_returns_paginated_kraken_universe(client, db_session):
    _seed_market(db_session, symbol="BTC-USD", base="BTC", status="ready", rows=80)
    _seed_market(db_session, symbol="ETH-USDT", base="ETH", status="backfill_pending", rows=0)
    _seed_market(db_session, symbol="USDC-USD", base="USDC", status="not_loaded", rows=0, analyzable=False, price=1)
    db_session.commit()

    response = client.get("/api/market/assets?exchange=kraken&scope=all&limit=500&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 500
    assert payload["offset"] == 0
    assert payload["counts"]["ready"] == 1
    assert payload["counts"]["statuses"]["not_loaded"] == 1
    assert [item["symbol"] for item in payload["items"]] == ["BTC-USD", "ETH-USDT", "USDC-USD"]
    assert payload["items"][0]["bot_eligible"] is True


def test_market_assets_ready_scope_filters_to_analyzable_ready_assets(client, db_session):
    _seed_market(db_session, symbol="BTC-USD", base="BTC", status="ready", rows=80)
    _seed_market(db_session, symbol="ETH-USDT", base="ETH", status="backfill_pending", rows=0)
    _seed_market(db_session, symbol="USDC-USD", base="USDC", status="ready", rows=80, analyzable=False, price=1)
    db_session.commit()

    response = client.get("/api/market/assets?exchange=kraken&scope=ready&limit=500&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["symbol"] == "BTC-USD"


def test_operations_can_queue_kraken_backfills(client, db_session, monkeypatch):
    _seed_market(db_session, symbol="BTC-USD", base="BTC", status="not_loaded", rows=0)
    db_session.commit()

    class FakeTask:
        id = "task-1"

    monkeypatch.setattr("app.services.exchange_markets.celery_app.send_task", lambda *args, **kwargs: FakeTask())

    response = client.post("/api/operations/market/backfill-kraken?limit=500")

    assert response.status_code == 200
    assert response.json()["queued"] == 1
    status = db_session.query(AssetDataStatus).filter(AssetDataStatus.symbol == "BTC-USD").one()
    assert status.status == "backfill_pending"
    assert status.last_backfill_task_id == "task-1"
