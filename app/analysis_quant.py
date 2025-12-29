from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

def calculate_risk_metrics(df: pd.DataFrame, risk_free_rate: float = 0.04) -> dict:
    """
    Calculate institutional-grade risk metrics for a given OHLCV DataFrame.
    
    Args:
        df: DataFrame with 'close' column and DatetimeIndex.
        risk_free_rate: Annualized risk-free rate (decimal, e.g. 0.04 for 4%).
        
    Returns:
        dict containing calculated metrics.
    """
    metrics = {
        "annualized_volatility": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "max_drawdown": None,
        "calmar_ratio": None,
        "omega_ratio": None,
        "skewness": None,
        "kurtosis": None
    }
    
    if df.empty or len(df) < 30:
        return metrics

    # Ensure close is numeric
    close = pd.to_numeric(df["close"], errors="coerce").fillna(method="ffill")
    
    # Calculate returns
    returns = close.pct_change().dropna()
    
    if len(returns) < 2:
        return metrics

    # Infer frequency to annualize
    # Crypto trades 365 days, 24/7.
    # If 1h data: 365 * 24 = 8760
    # If 1m data: 365 * 24 * 60 = 525600
    # If 1d data: 365
    
    # Simple heuristic based on median time delta
    if isinstance(df.index, pd.DatetimeIndex):
        diffs = df.index.to_series().diff().dropna()
        if not diffs.empty:
            median_diff = diffs.median()
            seconds = median_diff.total_seconds()
            
            if seconds <= 60: # 1m
                ann_factor = 365 * 24 * 60
            elif seconds <= 3600: # 1h
                ann_factor = 365 * 24
            elif seconds <= 86400: # 1d
                ann_factor = 365
            else:
                ann_factor = 365 # Default to daily if unsure or weekly
    else:
        # Fallback to daily
        ann_factor = 365

    # 1. Volatility (Annualized Standard Deviation)
    volatility = returns.std() * np.sqrt(ann_factor)
    metrics["annualized_volatility"] = round(volatility, 4)

    # 2. Sharpe Ratio (Excess Return / Volatility)
    # Adjust risk_free_rate to period
    rf_per_period = (1 + risk_free_rate) ** (1 / ann_factor) - 1
    excess_returns = returns - rf_per_period
    
    avg_excess_return = excess_returns.mean()
    std_excess_return = excess_returns.std()
    
    if std_excess_return > 0:
        sharpe = (avg_excess_return / std_excess_return) * np.sqrt(ann_factor)
        metrics["sharpe_ratio"] = round(sharpe, 4)
    else:
        metrics["sharpe_ratio"] = 0.0

    # 3. Sortino Ratio (Excess Return / Downside Deviation)
    downside_returns = excess_returns[excess_returns < 0]
    std_downside = downside_returns.std(ddof=1) # Sample std deviation of negative returns only? 
    # Usually Sortino uses root mean squared of downside deviations
    # Let's use standard formula: sqrt(mean(downside^2))
    
    downside_deviations = excess_returns.clip(upper=0) ** 2
    downside_std = np.sqrt(downside_deviations.mean())
    
    if downside_std > 0:
        sortino = (avg_excess_return / downside_std) * np.sqrt(ann_factor) * np.sqrt(2) # Sometimes adjusted, standard is just ann_factor
        # Actually standard Sortino annualization is same as Sharpe: multiply by sqrt(N)
        sortino = (excess_returns.mean() / downside_std) * np.sqrt(ann_factor)
        metrics["sortino_ratio"] = round(sortino, 4)
    else:
        metrics["sortino_ratio"] = 0.0

    # 4. Max Drawdown
    cumulative_returns = (1 + returns).cumprod()
    peak = cumulative_returns.expanding(min_periods=1).max()
    drawdown = (cumulative_returns / peak) - 1
    max_dd = drawdown.min()
    metrics["max_drawdown"] = round(max_dd, 4)
    
    # 5. Calmar Ratio (Annualized Return / Max Drawdown)
    total_return = (close.iloc[-1] / close.iloc[0]) - 1
    # Annualized return (CAGR equivalent for the period)
    # time_in_years = len(df) / ann_factor
    # cagr = (1 + total_return) ** (1/time_in_years) - 1
    
    # Simple annualized return for Calmar
    avg_return = returns.mean() * ann_factor
    if max_dd < 0:
        calmar = avg_return / abs(max_dd)
        metrics["calmar_ratio"] = round(calmar, 4)
        
    # 6. Skewness and Kurtosis
    metrics["skewness"] = round(returns.skew(), 4)
    metrics["kurtosis"] = round(returns.kurtosis(), 4)

    return metrics
