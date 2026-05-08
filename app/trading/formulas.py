from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

import numpy as np
import pandas as pd


TradeSide = Literal["long", "short"]


DEFAULT_SCORING_WEIGHTS: dict[str, dict[str, float]] = {
    "long_entry": {
        "price_above_vwap": 0.30,
        "rsi_mid": 0.25,
        "rsi_overbought_penalty": -0.15,
        "cvd_slope_positive": 0.20,
        "bullish_candle": 0.15,
        "volume_above_sma": 0.10,
    },
    "short_entry": {
        "price_below_vwap": 0.30,
        "rsi_mid": 0.20,
        "rsi_oversold_penalty": -0.15,
        "cvd_slope_negative": 0.25,
        "bearish_candle": 0.15,
        "volume_above_sma": 0.10,
    },
    "long_exit": {
        "price_below_vwap": 0.35,
        "rsi_overbought": 0.25,
        "cvd_slope_negative": 0.25,
        "bearish_candle": 0.15,
    },
    "short_exit": {
        "price_above_vwap": 0.35,
        "rsi_oversold": 0.25,
        "cvd_slope_positive": 0.25,
        "bullish_candle": 0.15,
    },
}


@dataclass(frozen=True)
class FormulaTargets:
    entry_price: float
    take_profit: float
    stop_loss: float
    reward_risk: float
    atr: float


def add_formula_indicators(
    df: pd.DataFrame,
    *,
    atr_length: int = 14,
    rsi_length: int = 14,
    cvd_length: int = 20,
    scoring_weights: Mapping[str, Mapping[str, float]] | None = None,
) -> pd.DataFrame:
    """Add deterministic day-trading formula inputs to an OHLCV DataFrame."""
    if df.empty:
        return df

    weights = _merge_scoring_weights(scoring_weights)
    data = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in data.columns:
            data[col] = 0.0
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0.0)

    prev_close = data["close"].shift(1)
    ranges = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - prev_close).abs(),
            (data["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    data["true_range"] = ranges.max(axis=1).fillna(data["high"] - data["low"])
    data["atr"] = data["true_range"].rolling(window=atr_length, min_periods=1).mean()

    delta = data["close"].diff()
    gain = delta.clip(lower=0).rolling(window=rsi_length, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(window=rsi_length, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_fallback = pd.Series(np.where(gain > 0, 100.0, 50.0), index=data.index)
    data["rsi"] = rsi.fillna(rsi_fallback)

    typical_price = (data["high"] + data["low"] + data["close"]) / 3.0
    cumulative_volume = data["volume"].cumsum().replace(0, np.nan)
    data["vwap"] = ((typical_price * data["volume"]).cumsum() / cumulative_volume).fillna(data["close"])
    data["price_vs_vwap_pct"] = np.where(
        data["vwap"] > 0,
        ((data["close"] / data["vwap"]) - 1.0) * 100,
        0.0,
    )

    data["signed_volume"] = _signed_volume(data)
    data["cvd"] = data["signed_volume"].cumsum()
    data["cvd_slope"] = data["cvd"].diff(cvd_length).fillna(data["cvd"].diff().fillna(0.0))
    data["volume_sma"] = data["volume"].rolling(window=20, min_periods=1).mean()

    data["long_entry_score"] = data.apply(lambda row: _long_entry_score(row, weights["long_entry"]), axis=1)
    data["short_entry_score"] = data.apply(lambda row: _short_entry_score(row, weights["short_entry"]), axis=1)
    data["long_exit_score"] = data.apply(lambda row: _long_exit_score(row, weights["long_exit"]), axis=1)
    data["short_exit_score"] = data.apply(lambda row: _short_exit_score(row, weights["short_exit"]), axis=1)
    return data


def formula_targets(
    entry_price: float,
    atr: float,
    side: TradeSide,
    *,
    stop_atr_multiplier: float = 1.5,
    target_atr_multiplier: float = 2.0,
    min_profit_pct: float = 0.012,
    max_stop_pct: float = 0.03,
) -> FormulaTargets:
    price = float(entry_price)
    atr_value = max(float(atr or 0.0), price * 0.0025)
    risk = min(max(atr_value * stop_atr_multiplier, price * 0.004), price * max_stop_pct)
    reward = max(atr_value * target_atr_multiplier, price * min_profit_pct)

    if side == "short":
        take_profit = max(0.00000001, price - reward)
        stop_loss = price + risk
    else:
        take_profit = price + reward
        stop_loss = max(0.00000001, price - risk)

    reward_risk = reward / risk if risk > 0 else 0.0
    return FormulaTargets(
        entry_price=round(price, 10),
        take_profit=round(take_profit, 10),
        stop_loss=round(stop_loss, 10),
        reward_risk=round(float(reward_risk), 4),
        atr=round(float(atr_value), 10),
    )


def kelly_fraction(
    win_rate: float,
    reward_risk: float,
    *,
    fractional: float = 0.25,
    cap: float = 0.35,
) -> float:
    w = min(max(float(win_rate or 0.0), 0.0), 1.0)
    r = max(float(reward_risk or 0.0), 0.0)
    if r <= 0:
        return 0.0
    full_kelly = w - ((1.0 - w) / r)
    if full_kelly <= 0:
        return 0.0
    return round(min(full_kelly * max(fractional, 0.0), cap), 6)


def sortino_ratio_from_returns(
    returns: pd.Series,
    *,
    risk_free_rate: float = 0.0,
    annualization_factor: int = 365 * 24 * 60,
) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return 0.0
    rf_per_period = (1 + risk_free_rate) ** (1 / annualization_factor) - 1 if annualization_factor > 0 else 0.0
    excess = values - rf_per_period
    downside = excess[excess < 0]
    if downside.empty:
        return 0.0
    downside_deviation = float(np.sqrt((downside**2).mean()))
    if downside_deviation <= 0:
        return 0.0
    return round(float((excess.mean() / downside_deviation) * np.sqrt(annualization_factor)), 4)


def formula_snapshot(
    row: pd.Series | dict[str, Any],
    *,
    side: TradeSide = "long",
    stop_atr_multiplier: float = 1.5,
    target_atr_multiplier: float | None = None,
    min_profit_pct: float | None = None,
    max_stop_pct: float = 0.03,
) -> dict[str, Any]:
    getter = row.get if hasattr(row, "get") else lambda key, default=None: default
    price = _safe_float(getter("close"))
    atr = _safe_float(getter("atr"))
    targets = formula_targets(
        price,
        atr,
        side,
        stop_atr_multiplier=stop_atr_multiplier,
        target_atr_multiplier=target_atr_multiplier if target_atr_multiplier is not None else (1.4 if side == "short" else 2.0),
        min_profit_pct=min_profit_pct if min_profit_pct is not None else (0.006 if side == "short" else 0.012),
        max_stop_pct=max_stop_pct,
    ) if price > 0 else None
    reward_risk = targets.reward_risk if targets else 0.0
    return {
        "side": side,
        "price": round(price, 10),
        "atr": round(atr, 10),
        "vwap": round(_safe_float(getter("vwap")), 10),
        "rsi": round(_safe_float(getter("rsi")), 4),
        "cvd": round(_safe_float(getter("cvd")), 4),
        "cvd_slope": round(_safe_float(getter("cvd_slope")), 4),
        "price_vs_vwap_pct": round(_safe_float(getter("price_vs_vwap_pct")), 4),
        "long_entry_score": round(_safe_float(getter("long_entry_score")), 4),
        "short_entry_score": round(_safe_float(getter("short_entry_score")), 4),
        "long_exit_score": round(_safe_float(getter("long_exit_score")), 4),
        "short_exit_score": round(_safe_float(getter("short_exit_score")), 4),
        "reward_risk": reward_risk,
        "take_profit": targets.take_profit if targets else None,
        "stop_loss": targets.stop_loss if targets else None,
        "funding_rate_arbitrage": {
            "enabled": False,
            "reason": "No futures funding-rate data source is configured.",
        },
    }


def _signed_volume(data: pd.DataFrame) -> pd.Series:
    if "side" in data.columns:
        side = data["side"].astype(str).str.lower()
        buy_volume = data["volume"].where(side.isin(("buy", "ask", "taker_buy")), 0.0)
        sell_volume = data["volume"].where(side.isin(("sell", "bid", "taker_sell")), 0.0)
        has_side = side.isin(("buy", "ask", "taker_buy", "sell", "bid", "taker_sell"))
        fallback = np.where(data["close"] >= data["open"], data["volume"], -data["volume"])
        return pd.Series(np.where(has_side, buy_volume - sell_volume, fallback), index=data.index)
    return pd.Series(np.where(data["close"] >= data["open"], data["volume"], -data["volume"]), index=data.index)


def _long_entry_score(row: pd.Series, weights: Mapping[str, float]) -> float:
    score = 0.0
    if _safe_float(row.get("close")) > _safe_float(row.get("vwap")):
        score += _score_weight(weights, "price_above_vwap")
    rsi = _safe_float(row.get("rsi"))
    if 48 <= rsi <= 72:
        score += _score_weight(weights, "rsi_mid")
    elif rsi > 72:
        score += _score_weight(weights, "rsi_overbought_penalty")
    if _safe_float(row.get("cvd_slope")) > 0:
        score += _score_weight(weights, "cvd_slope_positive")
    if _safe_float(row.get("close")) > _safe_float(row.get("open")):
        score += _score_weight(weights, "bullish_candle")
    if _safe_float(row.get("volume")) >= _safe_float(row.get("volume_sma")):
        score += _score_weight(weights, "volume_above_sma")
    return round(max(0.0, min(1.0, score)), 4)


def _short_entry_score(row: pd.Series, weights: Mapping[str, float]) -> float:
    score = 0.0
    if _safe_float(row.get("close")) < _safe_float(row.get("vwap")):
        score += _score_weight(weights, "price_below_vwap")
    rsi = _safe_float(row.get("rsi"))
    if 28 <= rsi <= 55:
        score += _score_weight(weights, "rsi_mid")
    elif rsi < 24:
        score += _score_weight(weights, "rsi_oversold_penalty")
    if _safe_float(row.get("cvd_slope")) < 0:
        score += _score_weight(weights, "cvd_slope_negative")
    if _safe_float(row.get("close")) < _safe_float(row.get("open")):
        score += _score_weight(weights, "bearish_candle")
    if _safe_float(row.get("volume")) >= _safe_float(row.get("volume_sma")):
        score += _score_weight(weights, "volume_above_sma")
    return round(max(0.0, min(1.0, score)), 4)


def _long_exit_score(row: pd.Series, weights: Mapping[str, float]) -> float:
    score = 0.0
    if _safe_float(row.get("close")) < _safe_float(row.get("vwap")):
        score += _score_weight(weights, "price_below_vwap")
    if _safe_float(row.get("rsi")) >= 78:
        score += _score_weight(weights, "rsi_overbought")
    if _safe_float(row.get("cvd_slope")) < 0:
        score += _score_weight(weights, "cvd_slope_negative")
    if _safe_float(row.get("close")) < _safe_float(row.get("open")):
        score += _score_weight(weights, "bearish_candle")
    return round(max(0.0, min(1.0, score)), 4)


def _short_exit_score(row: pd.Series, weights: Mapping[str, float]) -> float:
    score = 0.0
    if _safe_float(row.get("close")) > _safe_float(row.get("vwap")):
        score += _score_weight(weights, "price_above_vwap")
    if _safe_float(row.get("rsi")) <= 24:
        score += _score_weight(weights, "rsi_oversold")
    if _safe_float(row.get("cvd_slope")) > 0:
        score += _score_weight(weights, "cvd_slope_positive")
    if _safe_float(row.get("close")) > _safe_float(row.get("open")):
        score += _score_weight(weights, "bullish_candle")
    return round(max(0.0, min(1.0, score)), 4)


def _merge_scoring_weights(scoring_weights: Mapping[str, Mapping[str, float]] | None) -> dict[str, dict[str, float]]:
    merged = {group: dict(values) for group, values in DEFAULT_SCORING_WEIGHTS.items()}
    if not isinstance(scoring_weights, Mapping):
        return merged
    for group, values in scoring_weights.items():
        if group not in merged or not isinstance(values, Mapping):
            continue
        for key, value in values.items():
            try:
                merged[group][key] = float(value)
            except (TypeError, ValueError):
                continue
    return merged


def _score_weight(weights: Mapping[str, float], key: str) -> float:
    try:
        return float(weights.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(result):
        return 0.0
    return result
