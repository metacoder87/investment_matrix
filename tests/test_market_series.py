from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.market import MarketTrade


def test_market_series_bucketed(client, db_session):
    start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(seconds=10)

    db_session.add_all(
        [
            MarketTrade(
                exchange="coinbase",
                symbol="BTC-USD",
                timestamp=start + timedelta(seconds=1),
                receipt_timestamp=start + timedelta(seconds=1, milliseconds=10),
                price=Decimal("100.0"),
                amount=Decimal("0.1"),
                side="buy",
            ),
            MarketTrade(
                exchange="coinbase",
                symbol="BTC-USD",
                timestamp=start + timedelta(seconds=1, milliseconds=500),
                receipt_timestamp=start + timedelta(seconds=1, milliseconds=600),
                price=Decimal("101.0"),
                amount=Decimal("0.2"),
                side="sell",
            ),
            MarketTrade(
                exchange="coinbase",
                symbol="BTC-USD",
                timestamp=start + timedelta(seconds=7),
                receipt_timestamp=start + timedelta(seconds=7, milliseconds=10),
                price=Decimal("110.0"),
                amount=Decimal("0.05"),
                side="buy",
            ),
        ]
    )
    db_session.commit()

    resp = client.get(
        "/api/market/series/coinbase/BTC-USD",
        params={"start": start.isoformat(), "end": end.isoformat(), "max_points": 100},
    )
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["exchange"] == "coinbase"
    assert payload["symbol"] == "BTC-USD"
    assert payload["bucket_seconds"] == 1

    points = payload["points"]
    assert len(points) >= 2

    bucket_1s = (start + timedelta(seconds=1)).isoformat()
    point = next(p for p in points if p["timestamp"] == bucket_1s)
    assert point["trades"] == 2
    assert abs(point["price"] - 100.5) < 1e-9

