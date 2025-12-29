from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.market import MarketTrade


def test_market_candles_ohlcv_aggregation(client, db_session):
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
        "/api/market/candles/coinbase/BTC-USD",
        params={"start": start.isoformat(), "end": end.isoformat(), "timeframe": "1s", "max_points": 100},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["exchange"] == "coinbase"
    assert payload["symbol"] == "BTC-USD"
    assert payload["timeframe"] == "1s"
    assert payload["requested_bucket_seconds"] == 1
    assert payload["bucket_seconds"] == 1

    candles = payload["candles"]
    bucket_1s = (start + timedelta(seconds=1)).isoformat()
    candle = next(c for c in candles if c["timestamp"] == bucket_1s)
    assert candle["trades"] == 2
    assert abs(candle["open"] - 100.0) < 1e-9
    assert abs(candle["close"] - 101.0) < 1e-9
    assert abs(candle["high"] - 101.0) < 1e-9
    assert abs(candle["low"] - 100.0) < 1e-9
    assert abs(candle["volume"] - 0.3) < 1e-9

