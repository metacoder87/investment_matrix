from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.market import MarketTrade


def test_market_coverage_empty(client):
    resp = client.get("/api/market/coverage/coinbase/BTC-USD")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["exchange"] == "coinbase"
    assert payload["symbol"] == "BTC-USD"
    assert payload["trades"] == 0
    assert payload["first_timestamp"] is None
    assert payload["last_timestamp"] is None


def test_market_coverage_counts_and_range(client, db_session):
    now = datetime.now(timezone.utc).replace(microsecond=0)
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
                exchange="coinbase",
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

    resp = client.get("/api/market/coverage/coinbase/BTC-USD")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["trades"] == 2
    assert payload["first_timestamp"] < payload["last_timestamp"]

