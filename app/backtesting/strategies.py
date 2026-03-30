from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import pandas as pd
import pandas_ta as ta


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Strategy(Protocol):
    name: str

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    def generate_signals(self, df: pd.DataFrame) -> list[SignalAction]:
        ...


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


STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "sma_cross": SmaCrossStrategy,
    "rsi": RsiStrategy,
    "buy_hold": BuyHoldStrategy,
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
    return [
        {"name": "sma_cross", "params": {"short_window": 20, "long_window": 50}},
        {"name": "rsi", "params": {"length": 14, "buy_threshold": 30.0, "sell_threshold": 70.0}},
        {"name": "buy_hold", "params": {}},
    ]
