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


def _seed_formula_candles(db_session, symbol: str, start: datetime, prices: list[float]) -> datetime:
    previous = prices[0]
    for idx, price in enumerate(prices):
        ts = start + timedelta(minutes=idx)
        open_price = previous
        db_session.add(
            Price(
                symbol=symbol,
                exchange="coinbase",
                timestamp=ts,
                open=open_price,
                high=max(open_price, price) + 0.05,
                low=min(open_price, price) - 0.05,
                close=price,
                volume=10.0,
            )
        )
        previous = price
    db_session.commit()
    return start + timedelta(minutes=len(prices) - 1)


def test_paper_trading_step_executes_buy(client, db_session, auth_headers):
    start = datetime(2025, 1, 2, tzinfo=timezone.utc)
    prices = [10, 9, 8, 7, 6, 7, 8]
    end = _seed_prices(db_session, "ETH-USD", start, prices)

    resp = client.post(
        "/api/paper/accounts",
        headers=auth_headers,
        json={"name": "demo", "cash_balance": 1000.0},
    )
    assert resp.status_code == 200
    account_id = resp.json()["id"]

    step = client.post(
        f"/api/paper/accounts/{account_id}/step",
        headers=auth_headers,
        json={
            "symbol": "ETH-USD",
            "exchange": "coinbase",
            "timeframe": "1m",
            "lookback": 10,
            "as_of": end.isoformat(),
            "source": "prices",
            "strategy": "sma_cross",
            "strategy_params": {"short_window": 2, "long_window": 3},
        },
    )
    assert step.status_code == 200
    payload = step.json()
    assert payload["order"] is not None
    assert payload["order"]["side"] == "buy"
    assert payload["position"]["quantity"] > 0


def test_paper_trading_step_executes_paper_short(client, db_session, auth_headers):
    start = datetime(2025, 1, 3, tzinfo=timezone.utc)
    prices = [50.0] * 79 + [48.0]
    end = _seed_formula_candles(db_session, "XRP-USD", start, prices)

    resp = client.post(
        "/api/paper/accounts",
        headers=auth_headers,
        json={"name": "short-demo", "cash_balance": 2000.0},
    )
    assert resp.status_code == 200
    account_id = resp.json()["id"]

    step = client.post(
        f"/api/paper/accounts/{account_id}/step",
        headers=auth_headers,
        json={
            "symbol": "XRP-USD",
            "exchange": "coinbase",
            "timeframe": "1m",
            "lookback": 80,
            "as_of": end.isoformat(),
            "source": "prices",
            "strategy": "formula_quick_short",
            "strategy_params": {"entry_threshold": 0.4},
        },
    )

    assert step.status_code == 200
    payload = step.json()
    assert payload["order"]["side"] == "short"
    assert payload["position"]["side"] == "short"
    assert payload["position"]["quantity"] > 0
    assert payload["position"]["reserved_collateral"] > 0
    assert payload["cash_balance"] < 2000.0


def test_paper_schedule_run(client, db_session, auth_headers):
    start = datetime(2025, 1, 5, tzinfo=timezone.utc)
    prices = [100, 98, 96, 95, 94, 95, 96, 97]
    end = _seed_prices(db_session, "BTC-USD", start, prices)

    resp = client.post(
        "/api/paper/accounts",
        headers=auth_headers,
        json={"name": "schedule-demo", "cash_balance": 5000.0},
    )
    assert resp.status_code == 200
    account_id = resp.json()["id"]

    schedule_resp = client.post(
        "/api/paper/schedules",
        headers=auth_headers,
        json={
            "account_id": account_id,
            "symbol": "BTC-USD",
            "exchange": "coinbase",
            "timeframe": "1m",
            "lookback": 10,
            "source": "prices",
            "strategy": "sma_cross",
            "strategy_params": {"short_window": 2, "long_window": 3},
            "interval_seconds": 60,
        },
    )
    assert schedule_resp.status_code == 200
    schedule_id = schedule_resp.json()["id"]

    run_resp = client.post(
        f"/api/paper/schedules/{schedule_id}/run",
        headers=auth_headers,
        params={"as_of": end.isoformat()},
    )
    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert payload["result"]["status"] == "ok"
    assert payload["result"]["symbol"] == "BTC-USD"

