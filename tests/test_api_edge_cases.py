from fastapi.testclient import TestClient
from unittest.mock import MagicMock

import pytest

from app.main import (
    create_app,
    get_coinmarketcap_connector,
    get_coingecko_connector,
    get_db,
    get_news_connector,
)


@pytest.fixture
def edge_client():
    mock_db = MagicMock()
    mock_news = MagicMock()
    mock_cg = MagicMock()
    mock_cmc = MagicMock()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_news_connector] = lambda: mock_news
    app.dependency_overrides[get_coingecko_connector] = lambda: mock_cg
    app.dependency_overrides[get_coinmarketcap_connector] = lambda: mock_cmc

    with TestClient(app) as client:
        yield client, mock_db, mock_news, mock_cg, mock_cmc


def test_get_fundamentals_not_found(edge_client):
    client, _, _, mock_cg, mock_cmc = edge_client
    mock_cmc.get_fundamentals.return_value = None
    mock_cg.get_coin_fundamentals.return_value = None
    mock_cg.get_coin_id_by_symbol.return_value = None

    response = client.get("/api/coin/UNKNOWN-COIN/fundamentals")
    assert response.status_code == 404
    assert "Fundamentals not found" in response.json()["detail"]


def test_get_fundamentals_only_cg(edge_client):
    client, _, _, mock_cg, mock_cmc = edge_client
    mock_cmc.get_fundamentals.return_value = {"status": "error"}
    mock_cg.get_coin_fundamentals.return_value = {
        "market_cap": 1000,
        "fully_diluted_valuation": 2000,
        "total_supply": 100,
        "max_supply": 200,
        "description": "desc",
    }

    response = client.get("/api/coin/BTC/fundamentals?source=coinmarketcap")
    assert response.status_code == 200
    assert response.json()["market_cap"] == 1000


def test_quant_metrics_no_data_returns_empty_metrics(edge_client):
    client, mock_db, _, _, _ = edge_client
    mock_query = mock_db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_filter.group_by.return_value.all.return_value = []
    mock_filter.scalar.return_value = None

    response = client.get("/api/coin/NEW-TOKEN/quant")
    assert response.status_code == 200
    payload = response.json()
    assert "calculated_at" in payload
    assert payload["data"] == {
        "annualized_volatility": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "sortino_ratio": 0.0,
    }


def test_analysis_no_data_returns_empty_list(edge_client):
    client, mock_db, _, _, _ = edge_client
    mock_query = mock_db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_filter.group_by.return_value.all.return_value = []
    mock_filter.scalar.return_value = None

    response = client.get("/api/coin/NEW-TOKEN/analysis")
    assert response.status_code == 200
    assert response.json() == []


def test_signal_endpoint_no_data_returns_404(client):
    response = client.get("/api/signals/NEW-TOKEN")
    assert response.status_code == 404
    assert "Insufficient data" in response.json()["detail"]
