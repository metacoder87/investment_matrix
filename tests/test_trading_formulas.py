from __future__ import annotations

import pandas as pd

from app.trading.formulas import (
    add_formula_indicators,
    formula_targets,
    kelly_fraction,
    sortino_ratio_from_returns,
)


def test_formula_targets_long_and_short_use_atr_bands():
    long_targets = formula_targets(100.0, 2.0, "long")
    short_targets = formula_targets(100.0, 2.0, "short", target_atr_multiplier=1.4, min_profit_pct=0.006)

    assert long_targets.take_profit == 104.0
    assert long_targets.stop_loss == 97.0
    assert long_targets.reward_risk == 1.3333
    assert short_targets.take_profit == 97.2
    assert short_targets.stop_loss == 103.0
    assert short_targets.reward_risk == 0.9333


def test_formula_vwap_and_cvd_from_trade_side():
    df = pd.DataFrame(
        [
            {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 5, "side": "buy"},
            {"open": 10, "high": 12, "low": 10, "close": 12, "volume": 7, "side": "sell"},
            {"open": 12, "high": 13, "low": 11, "close": 13, "volume": 3, "side": "buy"},
        ]
    )

    result = add_formula_indicators(df, atr_length=2, rsi_length=2, cvd_length=1)

    assert round(result["vwap"].iloc[-1], 4) == 11.0889
    assert result["signed_volume"].tolist() == [5, -7, 3]
    assert result["cvd"].tolist() == [5, -2, 1]
    assert result["price_vs_vwap_pct"].iloc[-1] > 0


def test_formula_cvd_ohlcv_fallback_when_trade_side_missing():
    df = pd.DataFrame(
        [
            {"open": 10, "high": 11, "low": 9, "close": 11, "volume": 5},
            {"open": 11, "high": 11, "low": 9, "close": 10, "volume": 4},
        ]
    )

    result = add_formula_indicators(df)

    assert result["signed_volume"].tolist() == [5, -4]
    assert result["cvd"].tolist() == [5, 1]


def test_kelly_fraction_caps_and_zero_or_negative_edge_cases():
    assert kelly_fraction(0.6, 2.0, fractional=1.0, cap=0.2) == 0.2
    assert kelly_fraction(0.4, 1.0) == 0.0
    assert kelly_fraction(0.8, 0.0) == 0.0


def test_sortino_uses_downside_returns_only():
    assert sortino_ratio_from_returns(pd.Series([0.01, 0.02, 0.005])) == 0.0
    mixed = sortino_ratio_from_returns(pd.Series([0.01, -0.005, 0.002]), annualization_factor=365)
    assert mixed > 0
