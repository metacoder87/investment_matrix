from unittest.mock import MagicMock, patch

import pytest

def test_read_root(client):
    """Root returns API welcome message (Next.js is the primary frontend now)."""
    response = client.get("/")
    assert response.status_code == 200
    assert "CryptoInsight API is running" in response.json()["message"]


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.parametrize("client", [{"get_coingecko_connector": MagicMock(get_all_coins=MagicMock(return_value=[{"id": "bitcoin", "name": "Bitcoin"}]))}], indirect=True)
def test_get_coins_list(client):
    """Tests the /api/coins endpoint."""
    response = client.get("/api/coins")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json()[0]["id"] == "bitcoin"

@patch('celery_app.celery_app.send_task')
def test_start_price_ingestion(mock_send_task, client):
    """Tests starting the price ingestion task."""
    mock_async_result = MagicMock()
    mock_async_result.id = "test_task_id"
    mock_send_task.return_value = mock_async_result

    response = client.post("/api/ingest/prices/BTC/USDT")

    assert response.status_code == 202
    assert response.json() == {"message": "Price data ingestion task started.", "task_id": "test_task_id"}
    mock_send_task.assert_called_once_with(
        "celery_worker.tasks.ingest_historical_data",
        args=["BTC/USDT", "1m", 100],
        kwargs={"exchange_id": "binance"},
    )


@patch('celery_app.celery_app.send_task')
def test_start_coin_list_ingestion(mock_send_task, client):
    """Tests starting the coin list ingestion task."""
    mock_async_result = MagicMock()
    mock_async_result.id = "test_task_id_coins"
    mock_send_task.return_value = mock_async_result

    response = client.post("/api/ingest/coins")

    assert response.status_code == 202
    assert response.json() == {"message": "Coin list ingestion task started.", "task_id": "test_task_id_coins"}
    mock_send_task.assert_called_once_with("celery_worker.tasks.fetch_and_store_coin_list")
