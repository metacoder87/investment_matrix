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
        high = max(open_price, price) + 0.08
        low = min(open_price, price) - 0.08
        db_session.add(
            Price(
                symbol=symbol,
                exchange="coinbase",
                timestamp=ts,
                open=open_price,
                high=high,
                low=low,
                close=price,
                volume=10.0,
            )
        )
        previous = price
    db_session.commit()
    return start + timedelta(minutes=len(prices) - 1)


def test_backtest_sma_cross(client, db_session, auth_headers):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    prices = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8]
    end = _seed_prices(db_session, "BTC-USD", start, prices)

    resp = client.post(
        "/api/backtests",
        headers=auth_headers,
        json={
            "symbol": "BTC-USD",
            "exchange": "coinbase",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": "1m",
            "source": "prices",
            "strategy": "sma_cross",
            "strategy_params": {"short_window": 2, "long_window": 3},
            "initial_cash": 10_000.0,
            "include_trades": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["run_id"] > 0
    assert payload["metrics"]["trades"] >= 1
    assert payload["trades"] is not None


def test_formula_long_momentum_backtest_exits_with_profit(client, db_session, auth_headers):
    start = datetime(2025, 1, 3, tzinfo=timezone.utc)
    prices = [100 + idx * 0.18 for idx in range(80)]
    end = _seed_formula_candles(db_session, "SOL-USD", start, prices)

    resp = client.post(
        "/api/backtests",
        headers=auth_headers,
        json={
            "symbol": "SOL-USD",
            "exchange": "coinbase",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": "1m",
            "source": "prices",
            "strategy": "formula_long_momentum",
            "strategy_params": {},
            "initial_cash": 10_000.0,
            "max_position_pct": 0.5,
            "include_trades": True,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"]["side"] == "long"
    assert payload["metrics"]["sleeve"] == "long"
    assert "sortino_ratio" in payload["metrics"]
    assert payload["metrics"]["reward_risk"] > 0
    assert {trade["side"] for trade in payload["trades"]} >= {"buy", "sell"}


def test_formula_quick_short_backtest_covers_with_profit(client, db_session, auth_headers):
    start = datetime(2025, 1, 4, tzinfo=timezone.utc)
    prices = [120 - idx * 0.16 for idx in range(90)]
    end = _seed_formula_candles(db_session, "ADA-USD", start, prices)

    resp = client.post(
        "/api/backtests",
        headers=auth_headers,
        json={
            "symbol": "ADA-USD",
            "exchange": "coinbase",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": "1m",
            "source": "prices",
            "strategy": "formula_quick_short",
            "strategy_params": {},
            "initial_cash": 10_000.0,
            "max_position_pct": 0.5,
            "include_trades": True,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"]["side"] == "short"
    assert payload["metrics"]["sleeve"] == "short"
    assert payload["metrics"]["avg_trade_minutes"] >= 0
    assert {trade["side"] for trade in payload["trades"]} >= {"short", "cover"}
    assert any((trade["pnl"] or 0) > 0 for trade in payload["trades"] if trade["side"] == "cover")


def test_formula_dual_sleeve_backtest_reports_sleeve_metrics(client, db_session, auth_headers):
    start = datetime(2025, 1, 5, tzinfo=timezone.utc)
    up = [100 + idx * 0.18 for idx in range(50)]
    down = [up[-1] - idx * 0.18 for idx in range(1, 70)]
    end = _seed_formula_candles(db_session, "DOGE-USD", start, up + down)

    resp = client.post(
        "/api/backtests",
        headers=auth_headers,
        json={
            "symbol": "DOGE-USD",
            "exchange": "coinbase",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": "1m",
            "source": "prices",
            "strategy": "formula_dual_sleeve",
            "strategy_params": {},
            "initial_cash": 10_000.0,
            "max_position_pct": 0.5,
            "include_trades": True,
            "include_equity": True,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"]["side"] == "mixed"
    assert payload["metrics"]["sleeve"] == "dual"
    assert payload["metrics"]["bankroll_split"] == {"long": 0.5, "short": 0.5}
    assert set(payload["metrics"]["sleeves"]) == {"long", "short"}
    assert all(point["long_cash"] >= 0 and point["short_cash"] >= 0 for point in payload["equity_curve"])

