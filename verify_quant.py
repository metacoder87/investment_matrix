
import pandas as pd
import numpy as np
from app.analysis_quant import calculate_risk_metrics

def test_calculate_risk_metrics():
    print("Testing Quantitative Metrics...")
    
    # Create dummy OHLCV data with known trend/volatility
    dates = pd.date_range("2024-01-01", periods=100, freq="1D")
    # Linear growth with some noise
    close_prices = np.linspace(100, 200, 100) + np.random.normal(0, 2, 100)
    
    df = pd.DataFrame({
        "close": close_prices
    }, index=dates)
    
    metrics = calculate_risk_metrics(df, risk_free_rate=0.0)
    
    print(f"Metrics: {metrics}")
    
    # Assertions
    assert metrics["annualized_volatility"] > 0
    assert metrics["sharpe_ratio"] > 0 # Should be positive for uptrend
    assert metrics["max_drawdown"] <= 0
    
    # Test Sortino
    assert metrics["sortino_ratio"] is not None

if __name__ == "__main__":
    test_calculate_risk_metrics()
