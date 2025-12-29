from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.market import MarketTrade


def test_get_recent_trades_empty(client):
    response = client.get("/api/market/trades/BTC-USD")
    assert response.status_code == 200
    assert response.json() == []


def test_get_recent_trades_sorted_and_filtered(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            MarketTrade(
                exchange="coinbase",
                symbol="BTC-USD",
                timestamp=now - timedelta(seconds=2),
                receipt_timestamp=now - timedelta(seconds=1),
                price=Decimal("100.0"),
                amount=Decimal("0.1"),
                side="buy",
            ),
            MarketTrade(
                exchange="kraken",
                symbol="BTC-USD",
                timestamp=now - timedelta(seconds=1),
                receipt_timestamp=now,
                price=Decimal("101.0"),
                amount=Decimal("0.2"),
                side="sell",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/market/trades/BTC-USD", params={"limit": 10})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["exchange"] == "coinbase"
    assert data[1]["exchange"] == "kraken"
    assert data[0]["timestamp"] < data[1]["timestamp"]

    filtered = client.get("/api/market/trades/BTC-USD", params={"exchange": "coinbase"})
    assert filtered.status_code == 200
    data = filtered.json()
    assert len(data) == 1
    assert data[0]["exchange"] == "coinbase"

