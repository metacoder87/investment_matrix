import json
from unittest.mock import AsyncMock, patch


def test_list_exchanges(client):
    response = client.get("/api/exchanges")
    assert response.status_code == 200
    data = response.json()
    assert "streaming_supported" in data
    assert "ccxt_supported" in data
    assert "coinbase" in data["streaming_supported"]


def test_get_latest_tick_for_exchange(client):
    payload = {
        "exchange": "coinbase",
        "symbol": "BTC-USD",
        "ts": 1.0,
        "recv_ts": 2.0,
        "price": 100.0,
        "amount": 0.1,
        "side": "buy",
    }
    with patch("app.main.redis_client.get", new=AsyncMock(return_value=json.dumps(payload))):
        response = client.get("/api/market/latest/coinbase/BTC-USD")
    assert response.status_code == 200
    assert response.json()["exchange"] == "coinbase"

