from datetime import datetime, timedelta, timezone

from app.models.instrument import Price


def _seed_prices(db_session, symbol: str, start: datetime, prices: list[float]) -> datetime:
    for idx, price in enumerate(prices):
        ts = start + timedelta(minutes=idx)
        db_session.add(
            Price(
                symbol=symbol,
                exchange="coinbase",
                timestamp=ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1.0,
            )
        )
    db_session.commit()
    return start + timedelta(minutes=len(prices) - 1)


def test_walk_forward_backtest(client, db_session, auth_headers):
    start = datetime(2025, 1, 3, tzinfo=timezone.utc)
    prices = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9]
    end = _seed_prices(db_session, "BTC-USD", start, prices)

    resp = client.post(
        "/api/backtests/walk-forward",
        headers=auth_headers,
        json={
            "symbol": "BTC-USD",
            "exchange": "coinbase",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": "1m",
            "source": "prices",
            "train_window": 5,
            "test_window": 5,
            "step_window": 5,
            "strategy": "sma_cross",
            "strategy_params": {"short_window": 2, "long_window": 3},
            "store_report": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"]["windows"] >= 1
    assert payload["windows"][0]["baselines"]["buy_hold"] is not None

