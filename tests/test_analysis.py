import pandas as pd
import numpy as np
import pytest
from app.analysis import add_technical_indicators

@pytest.fixture
def sample_ohlcv_df():
    """
    Creates a sample pandas DataFrame with OHLCV data for testing.
    """
    data = {
        'timestamp': pd.to_datetime(np.arange(100), unit='D', origin='2023-01-01'),
        'high': np.random.uniform(102, 105, 100),
        'low': np.random.uniform(95, 98, 100),
        'open': np.random.uniform(98, 102, 100),
        'close': np.random.uniform(98, 105, 100),
        'volume': np.random.uniform(1000, 5000, 100)
    }
    df = pd.DataFrame(data)
    # Ensure close is float64 for talib
    df['close'] = df['close'].astype('float64')
    df['high'] = df['high'].astype('float64')
    df['low'] = df['low'].astype('float64')
    df['volume'] = df['volume'].astype('float64')
    return df

def test_add_technical_indicators(sample_ohlcv_df):
    """
    Tests that the add_technical_indicators function correctly adds indicator columns.
    """
    # When
    result_df = add_technical_indicators(sample_ohlcv_df)

    # Then
    assert not result_df.empty
    
    # Check if indicator columns are added
    # Check if indicator columns are added
    expected_columns = [
        'bbands_upper', 'bbands_middle', 'bbands_lower',
        'sma_50',
        'rsi',
        'macd', 'macdsignal', 'macdhist',
        'obv',
        'atr',
        'TSI_13_25_13' # Verify new pandas-ta indicator exists
    ]
    for col in expected_columns:
        assert col in result_df.columns
        # Check that there's at least one non-NaN value, indicating calculation occurred
        assert result_df[col].notna().any()

def test_add_technical_indicators_empty_df():
    """
    Tests that the function handles an empty DataFrame gracefully.
    """
    # Given
    empty_df = pd.DataFrame()

    # When
    result_df = add_technical_indicators(empty_df)

    # Then
    assert result_df.empty
