from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import pandas as pd
import pandas_ta as ta

from app.trading.formulas import add_formula_indicators


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"
    HOLD = "hold"


class Strategy(Protocol):
    name: str

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        ...


@dataclass
class StrategyMetadata:
    name: str
    required_indicators: list[str]
    minimum_candles: int
    supported_timeframes: list[str]
    allowed_order_types: list[str]
    default_risk: dict


@dataclass
class SmaCrossStrategy:
    short_window: int = 20
    long_window: int = 50
    name: str = "sma_cross"

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df["sma_fast"] = df["close"].rolling(window=self.short_window).mean()
        df["sma_slow"] = df["close"].rolling(window=self.long_window).mean()
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        signals: list[SignalAction] = []
        prev_fast = None
        prev_slow = None
        for _, row in df.iterrows():
            fast = row.get("sma_fast")
            slow = row.get("sma_slow")
            if pd.isna(fast) or pd.isna(slow) or prev_fast is None or prev_slow is None:
                signals.append(SignalAction.HOLD)
            elif prev_fast <= prev_slow and fast > slow:
                signals.append(SignalAction.BUY)
            elif prev_fast >= prev_slow and fast < slow:
                signals.append(SignalAction.SELL)
            else:
                signals.append(SignalAction.HOLD)
            prev_fast = fast
            prev_slow = slow
        return signals


@dataclass
class RsiStrategy:
    length: int = 14
    buy_threshold: float = 30.0
    sell_threshold: float = 70.0
    name: str = "rsi"

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df["rsi"] = ta.rsi(df["close"], length=self.length)
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        signals: list[SignalAction] = []
        for rsi_val in df["rsi"]:
            if pd.isna(rsi_val):
                signals.append(SignalAction.HOLD)
            elif rsi_val <= self.buy_threshold:
                signals.append(SignalAction.BUY)
            elif rsi_val >= self.sell_threshold:
                signals.append(SignalAction.SELL)
            else:
                signals.append(SignalAction.HOLD)
        return signals


@dataclass
class BuyHoldStrategy:
    name: str = "buy_hold"

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        if df.empty:
            return []
        return [SignalAction.BUY] + [SignalAction.HOLD] * (len(df) - 1)


@dataclass
class FormulaLongMomentumStrategy:
    atr_length: int = 14
    rsi_length: int = 14
    cvd_length: int = 20
    entry_threshold: float = 0.55
    exit_threshold: float = 0.55
    stop_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.0
    min_profit_pct: float = 0.012
    max_stop_pct: float = 0.03
    scoring_weights: dict | None = None
    name: str = "formula_long_momentum"

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_formula_indicators(
            df,
            atr_length=self.atr_length,
            rsi_length=self.rsi_length,
            cvd_length=self.cvd_length,
            scoring_weights=self.scoring_weights,
        )

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        signals: list[SignalAction] = []
        in_position = False
        for _, row in df.iterrows():
            entry_score = float(row.get("long_entry_score") or 0.0)
            exit_score = float(row.get("long_exit_score") or 0.0)
            if not in_position and entry_score >= self.entry_threshold:
                signals.append(SignalAction.BUY)
                in_position = True
            elif in_position and exit_score >= self.exit_threshold:
                signals.append(SignalAction.SELL)
                in_position = False
            else:
                signals.append(SignalAction.HOLD)
        return signals


@dataclass
class FormulaQuickShortStrategy:
    atr_length: int = 14
    rsi_length: int = 14
    cvd_length: int = 20
    entry_threshold: float = 0.55
    exit_threshold: float = 0.55
    stop_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 1.4
    min_profit_pct: float = 0.006
    max_stop_pct: float = 0.03
    scoring_weights: dict | None = None
    name: str = "formula_quick_short"

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_formula_indicators(
            df,
            atr_length=self.atr_length,
            rsi_length=self.rsi_length,
            cvd_length=self.cvd_length,
            scoring_weights=self.scoring_weights,
        )

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        signals: list[SignalAction] = []
        in_position = False
        for _, row in df.iterrows():
            entry_score = float(row.get("short_entry_score") or 0.0)
            exit_score = float(row.get("short_exit_score") or 0.0)
            if not in_position and entry_score >= self.entry_threshold:
                signals.append(SignalAction.SHORT)
                in_position = True
            elif in_position and exit_score >= self.exit_threshold:
                signals.append(SignalAction.COVER)
                in_position = False
            else:
                signals.append(SignalAction.HOLD)
        return signals


@dataclass
class FormulaDualSleeveStrategy:
    long_params: dict | None = None
    short_params: dict | None = None
    scoring_weights: dict | None = None
    name: str = "formula_dual_sleeve"

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_formula_indicators(df, scoring_weights=self.scoring_weights)

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        return [SignalAction.HOLD] * len(df)


STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "sma_cross": SmaCrossStrategy,
    "rsi": RsiStrategy,
    "buy_hold": BuyHoldStrategy,
    "formula_long_momentum": FormulaLongMomentumStrategy,
    "formula_quick_short": FormulaQuickShortStrategy,
    "formula_dual_sleeve": FormulaDualSleeveStrategy,
}

STRATEGY_METADATA: dict[str, StrategyMetadata] = {
    "sma_cross": StrategyMetadata(
        name="sma_cross",
        required_indicators=["sma_fast", "sma_slow"],
        minimum_candles=50,
        supported_timeframes=["1m", "5m", "15m", "1h", "4h", "1d"],
        allowed_order_types=["market"],
        default_risk={"max_position_pct": 0.10},
    ),
    "rsi": StrategyMetadata(
        name="rsi",
        required_indicators=["rsi"],
        minimum_candles=50,
        supported_timeframes=["1m", "5m", "15m", "1h", "4h", "1d"],
        allowed_order_types=["market"],
        default_risk={"max_position_pct": 0.10},
    ),
    "buy_hold": StrategyMetadata(
        name="buy_hold",
        required_indicators=[],
        minimum_candles=2,
        supported_timeframes=["1m", "5m", "15m", "1h", "4h", "1d"],
        allowed_order_types=["market"],
        default_risk={"max_position_pct": 1.0},
    ),
    "formula_long_momentum": StrategyMetadata(
        name="formula_long_momentum",
        required_indicators=["atr", "vwap", "rsi", "cvd", "long_entry_score", "long_exit_score"],
        minimum_candles=50,
        supported_timeframes=["1m", "5m", "15m"],
        allowed_order_types=["market"],
        default_risk={"sleeve": "long", "bankroll_pct": 0.50, "max_position_pct": 0.25},
    ),
    "formula_quick_short": StrategyMetadata(
        name="formula_quick_short",
        required_indicators=["atr", "vwap", "rsi", "cvd", "short_entry_score", "short_exit_score"],
        minimum_candles=50,
        supported_timeframes=["1m", "5m", "15m"],
        allowed_order_types=["market"],
        default_risk={"sleeve": "short", "bankroll_pct": 0.50, "max_position_pct": 0.20},
    ),
    "formula_dual_sleeve": StrategyMetadata(
        name="formula_dual_sleeve",
        required_indicators=["atr", "vwap", "rsi", "cvd"],
        minimum_candles=50,
        supported_timeframes=["1m", "5m", "15m"],
        allowed_order_types=["market"],
        default_risk={"bankroll_split": {"long": 0.50, "short": 0.50}},
    ),
}


def create_strategy(name: str, params: dict | None = None) -> Strategy:
    if not name:
        raise ValueError("strategy name is required")
    key = name.strip().lower()
    if key not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'")
    strategy_cls = STRATEGY_REGISTRY[key]
    params = params or {}
    return strategy_cls(**params)


def list_strategies() -> list[dict]:
    params = {
        "sma_cross": {"short_window": 20, "long_window": 50},
        "rsi": {"length": 14, "buy_threshold": 30.0, "sell_threshold": 70.0},
        "buy_hold": {},
        "formula_long_momentum": {"entry_threshold": 0.55, "exit_threshold": 0.55},
        "formula_quick_short": {"entry_threshold": 0.55, "exit_threshold": 0.55},
        "formula_dual_sleeve": {"long_params": {}, "short_params": {}},
    }
    return [
        {
            "name": name,
            "params": params[name],
            "required_indicators": metadata.required_indicators,
            "minimum_candles": metadata.minimum_candles,
            "supported_timeframes": metadata.supported_timeframes,
            "allowed_order_types": metadata.allowed_order_types,
            "default_risk": metadata.default_risk,
        }
        for name, metadata in STRATEGY_METADATA.items()
    ]
