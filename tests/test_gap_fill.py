import pytest
import asyncio
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
from app.services.backfill import StartupGapFiller

@pytest.mark.asyncio
async def test_gap_fill_triggered_for_old_data():
    # Arrange
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)
    
    mock_db_session = MagicMock()
    # Mock finding a timestamp from 2 hours ago
    mock_db_session.query.return_value.filter.return_value.scalar.return_value = two_hours_ago
    
    with patch("app.services.backfill.session_scope") as mock_scope, \
         patch("app.services.backfill.celery_app.send_task") as mock_send_task, \
         patch("app.services.backfill.settings.CORE_UNIVERSE", "BTC-USD"):
        
        mock_scope.return_value.__enter__.return_value = mock_db_session
        
        # Act
        await StartupGapFiller._check_and_fill()
        
        # Assert
        # Should have called backfill task with start_from = two_hours_ago
        mock_send_task.assert_called_once()
        args, kwargs = mock_send_task.call_args
        assert args[0] == "celery_worker.tasks.backfill_historical_candles"
        assert kwargs["kwargs"]["symbol"] == "BTC-USD"
        assert kwargs["kwargs"]["start_from"] == two_hours_ago.isoformat()

@pytest.mark.asyncio
async def test_no_gap_fill_for_fresh_data():
    # Arrange
    now = datetime.now(timezone.utc)
    two_mins_ago = now - timedelta(minutes=2)
    
    mock_db_session = MagicMock()
    # Mock finding a timestamp from 2 minutes ago
    mock_db_session.query.return_value.filter.return_value.scalar.return_value = two_mins_ago
    
    with patch("app.services.backfill.session_scope") as mock_scope, \
         patch("app.services.backfill.celery_app.send_task") as mock_send_task, \
         patch("app.services.backfill.settings.CORE_UNIVERSE", "BTC-USD"):
        
        mock_scope.return_value.__enter__.return_value = mock_db_session
        
        # Act
        await StartupGapFiller._check_and_fill()
        
        # Assert
        # Should NOT have called backfill task (gap < 5 mins)
        mock_send_task.assert_not_called()

@pytest.mark.asyncio
async def test_full_backfill_if_empty():
    # Arrange
    mock_db_session = MagicMock()
    # Mock finding NO data (None)
    mock_db_session.query.return_value.filter.return_value.scalar.return_value = None
    
    with patch("app.services.backfill.session_scope") as mock_scope, \
         patch("app.services.backfill.celery_app.send_task") as mock_send_task, \
         patch("app.services.backfill.settings.CORE_UNIVERSE", "BTC-USD"):
        
        mock_scope.return_value.__enter__.return_value = mock_db_session
        
        # Act
        await StartupGapFiller._check_and_fill()
        
        # Assert
        # Should call backfill with 'days=7' (default)
        mock_send_task.assert_called_once()
        args, kwargs = mock_send_task.call_args
        assert kwargs["kwargs"]["symbol"] == "BTC-USD"
        assert "start_from" not in kwargs["kwargs"]
        assert kwargs["kwargs"]["days"] == 7
