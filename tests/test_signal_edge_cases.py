import pytest
import pandas as pd
from unittest.mock import MagicMock
from app.signals.engine import SignalEngine
from app.connectors.sentiment import Sentiment

@pytest.fixture
def mock_sentiment():
    mock = MagicMock(spec=Sentiment)
    # Default to neutral/success
    mock.get_sentiment.return_value = {
        "score": 0.5, 
        "label": "Neutral", 
        "sources": {"stockgeist": 0, "santiment": 0}
    }
    return mock

@pytest.fixture
def engine(mock_sentiment):
    # We mock fetch_ohlcv to avoid DB calls
    # Pass MagicMock for db as well
    engine = SignalEngine(db=MagicMock(), sentiment_connector=mock_sentiment)
    return engine

def test_signal_generation_insufficient_data(engine):
    # Mock database query result using our new DI structure?
    # Actually, the engine queries the DB directly: self.db.query(...)
    # We need to mock the db session chaining: db.query().filter().order_by().limit().all()
    
    mock_query = engine.db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_order = mock_filter.order_by.return_value
    mock_limit = mock_order.limit.return_value
    mock_limit.all.return_value = [] # Empty list
    
    signal = engine.generate_signal("BTC-USD")
    
    # Should be None or a specialized "No Data" signal depending on implementation
    # Currently implementation returns None if df empty
    assert signal is None

def test_signal_generation_graceful_api_failure(engine, mock_sentiment):
    # API raises exception
    mock_sentiment.get_sentiment.side_effect = Exception("API Timeout")
    
    # Mock valid price data so signal generation proceeds
    dates = pd.date_range("2023-01-01", periods=100)
    # Create list of Price objects (mocks)
    prices = []
    for d in dates:
        p = MagicMock()
        p.timestamp = d
        p.open, p.high, p.low, p.close, p.volume = 100, 105, 95, 100, 1000
        prices.append(p)
        
    engine.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = prices
    
    # Should NOT raise exception, just ignore sentiment
    try:
        signal = engine.generate_signal("BTC-USD")
        assert signal is not None
        # Sentiment reasosn shouldn't be present
        assert not any("Sentiment" in r for r in signal.reasons)
    except Exception as e:
        pytest.fail(f"Engine crashed on API failure: {e}")

def test_signal_conflicting_indicators(engine):
    # Create a scenario where SMA suggests BUY (price > SMA) but RSI suggests SELL (Overbought)
    dates = pd.date_range("2023-01-01", periods=500)
    prices = []
    val = 100
    for i, d in enumerate(dates):
        val += 0.5 
        p = MagicMock()
        p.timestamp = d
        p.open = p.high = p.low = p.close = val
        p.volume = 1000
        prices.append(p)
    
    engine.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = prices
    
    signal = engine.generate_signal("BTC-USD")
    
    assert signal is not None
    # We expect some conflict in logic, likely a "Hold" or weak "Buy"/ "Sell"
    # But crucially, it should produce *some* signal and have reasons
    assert len(signal.reasons) > 0
    # Check if we have reasons from different indicators
    # RSI > 70 usually triggers sell in our engine
    # Price > SMA usually triggers buy
    # This is a qualitative check that logic ran
    print(f"Conflicting Signal: {signal.signal_type} - {signal.reasons}")
