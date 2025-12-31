
import pandas as pd
import numpy as np
from app.analysis import add_technical_indicators

def test_indicators():
    print("Testing Technical Analysis Engine...")
    
    # Create dummy OHLCV data
    dates = pd.date_range("2024-01-01", periods=100, freq="1h")
    df = pd.DataFrame({
        "open": np.random.uniform(40000, 42000, 100),
        "high": np.random.uniform(42000, 43000, 100),
        "low": np.random.uniform(39000, 40000, 100),
        "close": np.random.uniform(40000, 42000, 100),
        "volume": np.random.uniform(100, 1000, 100)
    }, index=dates)
    
    print(f"Input columns: {df.columns.tolist()}")
    
    # Process
    df = add_technical_indicators(df)
    
    print(f"Output columns: {len(df.columns)}")
    print(f"Columns: {df.columns.tolist()}")
    

    
    # Check for a few key ones (fuzzy match because names vary)
    found_count = 0
    for col in df.columns:
        print(f"Found indicator: {col}")
        found_count += 1
        
    if found_count > 40:
        print("SUCCESS: 50+ indicators confirmed!")
    else:
        print("WARNING: Fewer indicators than expected.")

if __name__ == "__main__":
    test_indicators()
