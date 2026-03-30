from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.engine import BacktestEngine
from app.backtesting.strategies import create_strategy, Strategy


@dataclass
class WalkForwardResult:
    summary: dict[str, Any]
    windows: list[dict[str, Any]]


def run_walk_forward(
    df: pd.DataFrame,
    strategy: Strategy,
    train_window: int,
    test_window: int,
    step_window: int | None,
    initial_cash: float,
    fee_rate: float,
    slippage_bps: float,
    max_position_pct: float,
    baseline_strategies: list[str] | None = None,
) -> WalkForwardResult:
    if df.empty:
        return WalkForwardResult(summary={}, windows=[])

    if train_window <= 0 or test_window <= 0:
        raise ValueError("train_window and test_window must be > 0")

    data = df.sort_values("timestamp").reset_index(drop=True)
    total_len = len(data)
    step = step_window or test_window
    if step <= 0:
        raise ValueError("step_window must be > 0")

    baseline_strategies = baseline_strategies or ["buy_hold", "sma_cross"]

    windows: list[dict[str, Any]] = []
    window_index = 0
    cursor = 0

    while cursor + train_window + test_window <= total_len:
        train_df = data.iloc[cursor : cursor + train_window]
        test_df = data.iloc[cursor + train_window : cursor + train_window + test_window]

        engine = BacktestEngine(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            max_position_pct=max_position_pct,
        )
        main_result = engine.run(test_df, strategy)

        baselines: dict[str, dict] = {}
        for baseline_name in baseline_strategies:
            baseline = create_strategy(baseline_name, {})
            baseline_result = engine.run(test_df, baseline)
            baselines[baseline_name] = baseline_result.metrics

        windows.append(
            {
                "index": window_index,
                "train_start": _to_iso(train_df["timestamp"].iloc[0]),
                "train_end": _to_iso(train_df["timestamp"].iloc[-1]),
                "test_start": _to_iso(test_df["timestamp"].iloc[0]),
                "test_end": _to_iso(test_df["timestamp"].iloc[-1]),
                "metrics": main_result.metrics,
                "baselines": baselines,
            }
        )

        window_index += 1
        cursor += step

    summary = _summarize_windows(windows, baseline_strategies)
    return WalkForwardResult(summary=summary, windows=windows)


def _summarize_windows(windows: list[dict], baselines: list[str]) -> dict[str, Any]:
    if not windows:
        return {}

    metric_keys = [
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate_pct",
        "profit_factor",
        "ending_equity",
    ]

    summary = {
        "windows": len(windows),
        "avg_metrics": _average_metrics(windows, metric_keys),
        "best_return_pct": _extreme_metric(windows, "total_return_pct", max),
        "worst_return_pct": _extreme_metric(windows, "total_return_pct", min),
    }

    baseline_summary = {}
    for baseline in baselines:
        baseline_summary[baseline] = _average_metrics(
            [
                {"metrics": window["baselines"].get(baseline, {})}
                for window in windows
            ],
            metric_keys,
        )

    summary["baseline_avg_metrics"] = baseline_summary
    return summary


def _average_metrics(windows: list[dict], keys: list[str]) -> dict[str, float]:
    averages = {}
    for key in keys:
        values = [window["metrics"].get(key) for window in windows]
        numeric = [float(v) for v in values if isinstance(v, (int, float))]
        averages[key] = round(float(np.mean(numeric)), 4) if numeric else 0.0
    return averages


def _extreme_metric(windows: list[dict], key: str, selector) -> float:
    values = [window["metrics"].get(key) for window in windows]
    numeric = [float(v) for v in values if isinstance(v, (int, float))]
    if not numeric:
        return 0.0
    return round(float(selector(numeric)), 4)


def _to_iso(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
