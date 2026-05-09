import json
import uuid

import pytest

from app.routers import portfolio as portfolio_router


class FakeRedis:
    def __init__(self, prices: dict[str, float] | None = None):
        self.prices = prices or {}

    async def mget(self, keys):
        values = []
        for key in keys:
            symbol = key.replace("latest:", "", 1)
            price = self.prices.get(symbol)
            values.append(json.dumps({"price": price}) if price is not None else None)
        return values


def _create_portfolio(client, auth_headers, name: str | None = None) -> int:
    response = client.post(
        "/api/portfolio/",
        headers=auth_headers,
        json={"name": name or f"Dashboard_{uuid.uuid4().hex[:8]}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _order(client, auth_headers, portfolio_id: int, symbol: str, side: str, price: float, amount: float):
    response = client.post(
        f"/api/portfolio/{portfolio_id}/orders",
        headers=auth_headers,
        json={
            "symbol": symbol,
            "exchange": "coinbase",
            "side": side,
            "price": price,
            "amount": amount,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_portfolio_dashboard_empty_state(client, auth_headers):
    response = client.get("/api/portfolio/dashboard", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "user"
    assert payload["portfolio_count"] == 0
    assert payload["total_equity"] == 0
    assert payload["total_cost"] == 0
    assert payload["closed_win_rate"] is None
    assert payload["positions"] == []
    assert payload["recent_orders"] == []


def test_portfolio_dashboard_reports_open_holdings_with_latest_prices(client, auth_headers, monkeypatch):
    monkeypatch.setattr(portfolio_router, "redis_client", FakeRedis({"BTC-USD": 150.0}))
    portfolio_id = _create_portfolio(client, auth_headers)
    _order(client, auth_headers, portfolio_id, "BTC-USD", "buy", 100.0, 2.0)

    response = client.get("/api/portfolio/dashboard", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_count"] == 1
    assert payload["total_equity"] == pytest.approx(300.0)
    assert payload["total_cost"] == pytest.approx(200.0)
    assert payload["unrealized_pnl"] == pytest.approx(100.0)
    assert payload["realized_pnl"] == pytest.approx(0.0)
    assert payload["all_time_pnl"] == pytest.approx(100.0)
    assert payload["open_positions"] == 1

    position = payload["positions"][0]
    assert position["symbol"] == "BTC-USD"
    assert position["side"] == "long"
    assert position["quantity"] == pytest.approx(2.0)
    assert position["last_price"] == pytest.approx(150.0)
    assert position["market_value"] == pytest.approx(300.0)
    assert position["return_pct"] == pytest.approx(50.0)


def test_portfolio_dashboard_aggregates_partial_sells_and_multi_portfolio_win_rate(
    client,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(portfolio_router, "redis_client", FakeRedis())
    first = _create_portfolio(client, auth_headers, "Manual Alpha")
    second = _create_portfolio(client, auth_headers, "Manual Beta")

    _order(client, auth_headers, first, "BTC-USD", "buy", 100.0, 2.0)
    _order(client, auth_headers, first, "BTC-USD", "sell", 120.0, 1.0)
    _order(client, auth_headers, second, "ETH-USD", "buy", 50.0, 1.0)
    _order(client, auth_headers, second, "ETH-USD", "sell", 40.0, 0.5)

    response = client.get("/api/portfolio/dashboard", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_count"] == 2
    assert payload["total_equity"] == pytest.approx(125.0)
    assert payload["total_cost"] == pytest.approx(125.0)
    assert payload["unrealized_pnl"] == pytest.approx(0.0)
    assert payload["realized_pnl"] == pytest.approx(15.0)
    assert payload["all_time_pnl"] == pytest.approx(15.0)
    assert payload["closed_trade_count"] == 2
    assert payload["closed_wins"] == 1
    assert payload["closed_losses"] == 1
    assert payload["closed_win_rate"] == pytest.approx(0.5)
    assert payload["open_positions"] == 2
    assert {position["symbol"] for position in payload["positions"]} == {"BTC-USD", "ETH-USD"}

    recent = payload["recent_orders"]
    assert len(recent) == 4
    sell_orders = [order for order in recent if order["side"] == "sell"]
    assert {order["portfolio_name"] for order in sell_orders} == {"Manual Alpha", "Manual Beta"}
    assert sorted(order["realized_pnl"] for order in sell_orders) == pytest.approx([-5.0, 20.0])
