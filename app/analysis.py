from __future__ import annotations

import pandas as pd


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a rich set of technical indicators to an OHLCV DataFrame using pandas-ta.
    Sequential implementation to avoid Strategy object dependency issues.
    
    Expected columns: `open`, `high`, `low`, `close`, `volume`.
    """
    if df.empty:
        return df

    # Ensure columns are numeric and proper case
    # pandas-ta needs lowercase columns usually
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # --- 1. Momentum ---
    df.ta.rsi(length=14, append=True)
    df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
    df.ta.tsi(fast=13, slow=25, append=True)
    df.ta.uo(append=True) # Ultimate Oscillator
    df.ta.ao(append=True) # Awesome Oscillator
    df.ta.mfi(length=14, append=True)
    df.ta.willr(length=14, append=True)
    df.ta.cmo(length=14, append=True)
    
    # --- 2. Trend ---
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)
    
    # EMAs (Need explicit naming or handling default names)
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.ema(length=55, append=True)
    
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.adx(length=14, append=True)
    df.ta.vortex(length=14, append=True)
    df.ta.supertrend(length=10, multiplier=3.0, append=True)
    # df.ta.ichimoku(append=True) # Returns tuple, tricky with append=True sometimes, skipping for now
    df.ta.psar(append=True)
    
    # --- 3. Volatility ---
    df.ta.atr(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.kc(length=20, append=True) # Keltner Channels
    df.ta.donchian(lower_length=20, upper_length=20, append=True)
    
    # --- 4. Volume ---
    df.ta.obv(append=True)
    # df.ta.vwap(append=True) # Requires 'high', 'low', 'close', 'volume' and strictly datetime index? 
    # Usually safer to call explicitly if index is not guaranteed
    if isinstance(df.index, pd.DatetimeIndex):
         try:
             df.ta.vwap(append=True)
         except Exception:
             pass

    df.ta.cmf(length=20, append=True)
    df.ta.adosc(open=3, fast=10, append=True)
    
    # --- 5. Cycles ---
    try:
        df.ta.ebsw(append=True)
    except:
        pass

    # --- Backwards Compatibility Renames ---
    # The Signals Engine expects specific names like "rsi", "macd", etc.
    # pandas-ta usually appends length, e.g. "RSI_14".
    # We will map them to the simple names our app uses.
    
    # Helper to find column matching a pattern
    def get_col(prefix):
        # find col starting with prefix
        candidates = [c for c in df.columns if c.startswith(prefix)]
        if candidates:
            return candidates[-1] # closest to end (most recent calc)
        return None

    # Map: Simple Name -> Pandas-Ta Generated Name (dynamic find)
    rename_map = {
        "rsi": "RSI_14",
        "mfi": "MFI_14",
        "sma_50": "SMA_50",
        "sma_200": "SMA_200",
        "macd": "MACD_12_26_9",
        "macdsignal": "MACDs_12_26_9",
        "macdhist": "MACDh_12_26_9",
        "bbands_upper": "BBU_20_2.0_2.0",
        "bbands_middle": "BBM_20_2.0_2.0", 
        "bbands_lower": "BBL_20_2.0_2.0",
        "atr": "ATRr_14",
        "obv": "OBV"
    }

    for simple, pta_name in rename_map.items():
        if pta_name in df.columns:
            df[simple] = df[pta_name]
        else:
            # Fallback: exact match failed, try fuzzy
            # e.g. ATRe_14 vs ATRr_14
            pass

    return df
