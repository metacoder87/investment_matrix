import pytest
import pandas as pd
import numpy as np
from app.analysis_quant import calculate_risk_metrics

@pytest.fixture
def uptrend_df():
    """Steady uptrend: Low volatility, high return."""
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    prices = np.linspace(100, 200, 100) # Doubles in value
    return pd.DataFrame({"close": prices}, index=dates)

@pytest.fixture
def downtrend_df():
    """Steady downtrend: Negative return."""
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    prices = np.linspace(200, 100, 100) # Halves in value
    return pd.DataFrame({"close": prices}, index=dates)

@pytest.fixture
def volatile_df():
    """High volatility, flat return."""
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    # Alternating 100, 110, 100, 110...
    prices = [100 if i % 2 == 0 else 110 for i in range(100)]
    return pd.DataFrame({"close": prices}, index=dates)

def test_calculate_risk_metrics_uptrend(uptrend_df):
    metrics = calculate_risk_metrics(uptrend_df)
    
    # Check for keys existing
    assert "sharpe_ratio" in metrics
    assert metrics["sharpe_ratio"] is not None and metrics["sharpe_ratio"] > 2.0
    assert metrics["max_drawdown"] == 0.0 # No drawdown in a straight line up
    assert metrics["annualized_volatility"] < 0.1 

def test_calculate_risk_metrics_downtrend(downtrend_df):
    metrics = calculate_risk_metrics(downtrend_df)
    
    assert metrics["sharpe_ratio"] is not None and metrics["sharpe_ratio"] < 0 # Negative return
    assert metrics["max_drawdown"] < -0.4 # Starts 200, ends 100 -> -50% drawdown

def test_calculate_risk_metrics_volatile(volatile_df):
    metrics = calculate_risk_metrics(volatile_df)
    
    # Volatility should be significant
    assert metrics["annualized_volatility"] > 0.0
    
def test_calculate_risk_metrics_empty():
    empty_df = pd.DataFrame(columns=["close"])
    metrics = calculate_risk_metrics(empty_df)
    
    # Implementation returns None for insufficient data
    assert metrics["sharpe_ratio"] is None
    assert metrics["max_drawdown"] is None

def test_calculate_risk_metrics_single_point():
    dates = pd.date_range(start="2023-01-01", periods=1, freq="D")
    df = pd.DataFrame({"close": [100]}, index=dates)
    metrics = calculate_risk_metrics(df)
    
    # Less than 30 points -> None
    assert metrics["annualized_volatility"] is None
    assert metrics["sharpe_ratio"] is None
