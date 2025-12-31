import pytest
from unittest.mock import MagicMock, patch
from celery_worker.tasks import backfill_core_universe, ingest_historical_data

@patch("celery_worker.tasks.backfill_historical_candles")
@patch("celery_worker.tasks.celery_app")
@patch("celery_worker.tasks.session_scope")
def test_backfill_core_universe(mock_session_scope, mock_celery_app, mock_subtask):
    """Test that backfill_core_universe chains tasks correctly."""
    
    # Mock behavior
    mock_db = MagicMock()
    mock_session_scope.return_value.__enter__.return_value = mock_db
    mock_subtask.delay.return_value.id = "mock_id"
    
    # Run task
    result = backfill_core_universe(exchange_id="coinbase", days=7)
    
    # Assertions
    assert "queued" in result["status"]

@patch("celery_worker.tasks.backfill_historical_candles")
def test_backfill_core_universe_logic(mock_task):
    """Test that backfill_core_universe calls the sub-task."""
    mock_task.delay.return_value.id = "mock_id"
    
    result = backfill_core_universe(exchange_id="coinbase", days=7)
    
    assert result["status"] == "queued"
    assert len(result["tasks"]) == 5 # Default 5 symbols
    assert mock_task.delay.call_count == 5

def test_ingest_historical_data_mock():
    # We also need to patch session_scope inside the function or module
    with patch("celery_worker.tasks.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = MagicMock()
        
        with patch("celery_worker.tasks.ccxt") as mock_ccxt:
            # Simulate exchange construction error
            mock_ccxt.binance.side_effect = Exception("Network Error")
            
            # Assert it raises the network error
            with pytest.raises(Exception):
                ingest_historical_data("BTC/USDT", "1h", 100, "binance")
