from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.execution import (
    ExecutionSettings,
    compute_buy_fill,
    compute_sell_fill,
    compute_short_cover_fill,
    compute_short_open_fill,
)
from app.backtesting.strategies import (
    FormulaLongMomentumStrategy,
    FormulaQuickShortStrategy,
    SignalAction,
    Strategy,
)
from app.trading.formulas import formula_snapshot, formula_targets, kelly_fraction, sortino_ratio_from_returns


@dataclass
class TradeRecord:
    timestamp: datetime
    side: str
    price: float
    quantity: float
    fee: float
    cash_balance: float
    equity: float
    pnl: float | None = None
    reason: str | None = None
    sleeve: str | None = None
    reward_risk: float | None = None
    entry_score: float | None = None
    exit_score: float | None = None


@dataclass
class BacktestResult:
    metrics: dict
    trades: list[TradeRecord]
    equity_curve: list[dict]


class BacktestEngine:
    def __init__(
        self,
        initial_cash: float,
        fee_rate: float,
        slippage_bps: float,
        max_position_pct: float,
        min_trade_value: float = 10.0,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.execution = ExecutionSettings(
            fee_rate=float(fee_rate),
            slippage_bps=float(slippage_bps),
            max_position_pct=float(max_position_pct),
            min_trade_value=float(min_trade_value),
        )

    def run(self, df: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        if df.empty:
            return BacktestResult(metrics=_empty_metrics(), trades=[], equity_curve=[])

        if getattr(strategy, "name", "") == "formula_dual_sleeve":
            return self._run_dual_sleeve(df, strategy)

        data = _prepare_data(df, strategy)
        signals = strategy.generate_signals(data)
        if len(signals) != len(data):
            raise ValueError("Signals length mismatch with data length")

        cash = self.initial_cash
        position_side: str | None = None
        position_qty = 0.0
        entry_cost = None
        entry_price = None
        entry_ts: datetime | None = None
        reserved_collateral = 0.0
        take_profit = None
        stop_loss = None
        reward_risk = None
        trailing_peak = None
        trailing_trough = None
        sleeve = _sleeve_for_strategy(strategy)

        equity_curve: list[dict] = []
        trades: list[TradeRecord] = []
        realized_pnls: list[float] = []
        trade_durations: list[float] = []
        latest_formula_snapshot: dict[str, Any] | None = None

        for idx, row in data.iterrows():
            ts = _normalize_ts(row["timestamp"])
            price = float(row["close"])
            high = float(row.get("high", price) or price)
            low = float(row.get("low", price) or price)
            signal = signals[idx]

            if position_side == "long":
                trailing_peak = max(float(trailing_peak or entry_price or price), high)
                if getattr(strategy, "name", "").startswith("formula_"):
                    trailing_stop = trailing_peak * 0.994
                    stop_loss = max(float(stop_loss or trailing_stop), trailing_stop)

                exit_reason = None
                exit_price = price
                if stop_loss is not None and low <= stop_loss:
                    exit_reason = "stop_loss"
                    exit_price = float(stop_loss)
                elif take_profit is not None and high >= take_profit:
                    exit_reason = "take_profit"
                    exit_price = float(take_profit)
                elif signal == SignalAction.SELL:
                    exit_reason = "signal_exit"

                if exit_reason and position_qty > 0:
                    fill = compute_sell_fill(position_qty, exit_price, self.execution)
                    if fill:
                        cash += fill.cash_delta
                        pnl = fill.notional - fill.fee - float(entry_cost or 0.0)
                        realized_pnls.append(pnl)
                        if entry_ts is not None:
                            trade_durations.append(max(0.0, (ts - entry_ts).total_seconds() / 60))
                        position_qty = 0.0
                        position_side = None
                        entry_cost = None
                        entry_price = None
                        entry_ts = None
                        trades.append(
                            TradeRecord(
                                timestamp=ts,
                                side=SignalAction.SELL.value,
                                price=fill.price,
                                quantity=fill.quantity,
                                fee=fill.fee,
                                cash_balance=cash,
                                equity=cash,
                                pnl=pnl,
                                reason=exit_reason,
                                sleeve=sleeve,
                                reward_risk=reward_risk,
                                exit_score=_safe_float(row.get("long_exit_score")),
                            )
                        )
                        take_profit = None
                        stop_loss = None
                        reward_risk = None
                        trailing_peak = None

            elif position_side == "short":
                trailing_trough = min(float(trailing_trough or entry_price or price), low)
                if getattr(strategy, "name", "").startswith("formula_"):
                    trailing_stop = trailing_trough * 1.004
                    stop_loss = min(float(stop_loss or trailing_stop), trailing_stop)

                exit_reason = None
                exit_price = price
                if stop_loss is not None and high >= stop_loss:
                    exit_reason = "short_stop_loss"
                    exit_price = float(stop_loss)
                elif take_profit is not None and low <= take_profit:
                    exit_reason = "short_take_profit"
                    exit_price = float(take_profit)
                elif signal == SignalAction.COVER:
                    exit_reason = "signal_cover"

                if exit_reason and position_qty > 0 and entry_price is not None:
                    fill = compute_short_cover_fill(
                        position_qty,
                        entry_price,
                        reserved_collateral,
                        exit_price,
                        self.execution,
                    )
                    if fill:
                        cash += fill.cash_delta
                        pnl = fill.pnl
                        realized_pnls.append(pnl)
                        if entry_ts is not None:
                            trade_durations.append(max(0.0, (ts - entry_ts).total_seconds() / 60))
                        position_qty = 0.0
                        position_side = None
                        entry_price = None
                        entry_ts = None
                        reserved_collateral = 0.0
                        trades.append(
                            TradeRecord(
                                timestamp=ts,
                                side=SignalAction.COVER.value,
                                price=fill.price,
                                quantity=fill.quantity,
                                fee=fill.fee,
                                cash_balance=cash,
                                equity=cash,
                                pnl=pnl,
                                reason=exit_reason,
                                sleeve=sleeve,
                                reward_risk=reward_risk,
                                exit_score=_safe_float(row.get("short_exit_score")),
                            )
                        )
                        take_profit = None
                        stop_loss = None
                        reward_risk = None
                        trailing_trough = None

            if position_side is None:
                equity = cash
                if signal == SignalAction.BUY:
                    fill = compute_buy_fill(cash, equity, price, self.execution)
                    if fill:
                        targets = _targets_for_entry(row, fill.price, "long", strategy)
                        cash += fill.cash_delta
                        position_qty = fill.quantity
                        position_side = "long"
                        entry_cost = fill.notional + fill.fee
                        entry_price = fill.price
                        entry_ts = ts
                        take_profit = targets.take_profit
                        stop_loss = targets.stop_loss
                        reward_risk = targets.reward_risk
                        trailing_peak = fill.price
                        latest_formula_snapshot = formula_snapshot(row, side="long")
                        trades.append(
                            TradeRecord(
                                timestamp=ts,
                                side=SignalAction.BUY.value,
                                price=fill.price,
                                quantity=fill.quantity,
                                fee=fill.fee,
                                cash_balance=cash,
                                equity=_mark_equity(cash, position_side, position_qty, price, entry_price, reserved_collateral),
                                reason=strategy.name,
                                sleeve=sleeve,
                                reward_risk=reward_risk,
                                entry_score=_safe_float(row.get("long_entry_score")),
                            )
                        )

                elif signal == SignalAction.SHORT:
                    fill = compute_short_open_fill(cash, equity, price, self.execution)
                    if fill:
                        targets = _targets_for_entry(row, fill.price, "short", strategy)
                        cash += fill.cash_delta
                        position_qty = fill.quantity
                        position_side = "short"
                        entry_price = fill.price
                        entry_ts = ts
                        reserved_collateral = fill.notional
                        take_profit = targets.take_profit
                        stop_loss = targets.stop_loss
                        reward_risk = targets.reward_risk
                        trailing_trough = fill.price
                        latest_formula_snapshot = formula_snapshot(row, side="short")
                        trades.append(
                            TradeRecord(
                                timestamp=ts,
                                side=SignalAction.SHORT.value,
                                price=fill.price,
                                quantity=fill.quantity,
                                fee=fill.fee,
                                cash_balance=cash,
                                equity=_mark_equity(cash, position_side, position_qty, price, entry_price, reserved_collateral),
                                reason=strategy.name,
                                sleeve=sleeve,
                                reward_risk=reward_risk,
                                entry_score=_safe_float(row.get("short_entry_score")),
                            )
                        )

            equity = _mark_equity(cash, position_side, position_qty, price, entry_price, reserved_collateral)
            equity_curve.append(
                {
                    "timestamp": _ensure_iso(ts),
                    "equity": equity,
                    "cash": cash,
                    "position_qty": position_qty,
                    "position_side": position_side,
                    "entry_price": entry_price,
                    "reserved_collateral": reserved_collateral if position_side == "short" else 0.0,
                    "take_profit": take_profit,
                    "stop_loss": stop_loss,
                    "sleeve": sleeve,
                    "formula_snapshot": formula_snapshot(row, side="short" if position_side == "short" else "long")
                    if getattr(strategy, "name", "").startswith("formula_")
                    else None,
                }
            )

        metrics = _compute_metrics(
            equity_curve,
            trades,
            realized_pnls,
            self.initial_cash,
            trade_durations=trade_durations,
            sleeve=sleeve,
            formula_snapshot_value=latest_formula_snapshot,
        )
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)

    def _run_dual_sleeve(self, df: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        long_params = getattr(strategy, "long_params", None) or {}
        short_params = getattr(strategy, "short_params", None) or {}
        long_result = BacktestEngine(
            initial_cash=self.initial_cash * 0.5,
            fee_rate=self.execution.fee_rate,
            slippage_bps=self.execution.slippage_bps,
            max_position_pct=self.execution.max_position_pct,
            min_trade_value=self.execution.min_trade_value,
        ).run(df, FormulaLongMomentumStrategy(**long_params))
        short_result = BacktestEngine(
            initial_cash=self.initial_cash * 0.5,
            fee_rate=self.execution.fee_rate,
            slippage_bps=self.execution.slippage_bps,
            max_position_pct=self.execution.max_position_pct,
            min_trade_value=self.execution.min_trade_value,
        ).run(df, FormulaQuickShortStrategy(**short_params))

        equity_curve = _combine_equity_curves(long_result.equity_curve, short_result.equity_curve)
        trades = sorted(long_result.trades + short_result.trades, key=lambda trade: trade.timestamp)
        realized_pnls = [float(trade.pnl) for trade in trades if trade.pnl is not None]
        metrics = _compute_metrics(equity_curve, trades, realized_pnls, self.initial_cash, sleeve="dual")
        metrics["sleeves"] = {
            "long": long_result.metrics,
            "short": short_result.metrics,
        }
        metrics["bankroll_split"] = {"long": 0.5, "short": 0.5}
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)


def _prepare_data(df: pd.DataFrame, strategy: Strategy) -> pd.DataFrame:
    data = df.copy()
    if "timestamp" not in data.columns:
        raise ValueError("DataFrame must include a timestamp column")
    data = data.sort_values("timestamp").reset_index(drop=True)
    return strategy.prepare(data)


def _targets_for_entry(row: pd.Series, entry_price: float, side: str, strategy: Strategy):
    return formula_targets(
        entry_price,
        _safe_float(row.get("atr")),
        "short" if side == "short" else "long",
        stop_atr_multiplier=float(getattr(strategy, "stop_atr_multiplier", 1.5) or 1.5),
        target_atr_multiplier=float(getattr(strategy, "target_atr_multiplier", 1.4 if side == "short" else 2.0) or (1.4 if side == "short" else 2.0)),
        min_profit_pct=float(getattr(strategy, "min_profit_pct", 0.006 if side == "short" else 0.012) or (0.006 if side == "short" else 0.012)),
        max_stop_pct=float(getattr(strategy, "max_stop_pct", 0.03) or 0.03),
    )


def _sleeve_for_strategy(strategy: Strategy) -> str:
    if getattr(strategy, "name", "") == "formula_quick_short":
        return "short"
    if getattr(strategy, "name", "") == "formula_dual_sleeve":
        return "dual"
    return "long"


def _mark_equity(
    cash: float,
    position_side: str | None,
    quantity: float,
    price: float,
    entry_price: float | None,
    reserved_collateral: float,
) -> float:
    if position_side == "long":
        return cash + quantity * price
    if position_side == "short" and entry_price is not None:
        return cash + reserved_collateral + (entry_price - price) * quantity
    return cash


def _combine_equity_curves(long_curve: list[dict], short_curve: list[dict]) -> list[dict]:
    combined: list[dict] = []
    for long_point, short_point in zip(long_curve, short_curve):
        combined.append(
            {
                "timestamp": long_point["timestamp"],
                "equity": float(long_point["equity"]) + float(short_point["equity"]),
                "cash": float(long_point["cash"]) + float(short_point["cash"]),
                "long_equity": long_point["equity"],
                "short_equity": short_point["equity"],
                "long_cash": long_point.get("cash", 0.0),
                "short_cash": short_point.get("cash", 0.0),
                "long_position_qty": long_point.get("position_qty", 0.0),
                "short_position_qty": short_point.get("position_qty", 0.0),
                "long_reserved_collateral": long_point.get("reserved_collateral", 0.0),
                "short_reserved_collateral": short_point.get("reserved_collateral", 0.0),
                "sleeve": "dual",
            }
        )
    return combined


def _ensure_iso(ts: datetime) -> str:
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        return ts.isoformat() + "Z"
    return ts.isoformat()


def _normalize_ts(ts: datetime) -> datetime:
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    return ts


def _compute_metrics(
    equity_curve: list[dict],
    trades: list[TradeRecord],
    realized_pnls: list[float],
    initial_cash: float,
    *,
    trade_durations: list[float] | None = None,
    sleeve: str = "long",
    formula_snapshot_value: dict[str, Any] | None = None,
) -> dict:
    if not equity_curve:
        return _empty_metrics()

    equity_series = pd.Series(
        [point["equity"] for point in equity_curve],
        index=pd.to_datetime([point["timestamp"] for point in equity_curve], utc=True),
    )
    returns = equity_series.pct_change().dropna()

    total_return = (equity_series.iloc[-1] / initial_cash - 1) * 100

    running_max = equity_series.cummax()
    drawdowns = equity_series / running_max - 1
    max_drawdown = drawdowns.min() if not drawdowns.empty else 0.0

    ann_factor = _infer_annualization_factor(equity_series.index)
    if returns.std() > 0 and ann_factor > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(ann_factor)
    else:
        sharpe = 0.0
    sortino = sortino_ratio_from_returns(returns, annualization_factor=ann_factor)

    exits = [t for t in trades if t.side in {SignalAction.SELL.value, SignalAction.COVER.value}]
    wins = [pnl for pnl in realized_pnls if pnl > 0]
    losses = [pnl for pnl in realized_pnls if pnl <= 0]
    win_rate = (len(wins) / len(realized_pnls)) * 100 if realized_pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else float("inf") if wins else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = abs(float(np.mean(losses))) if losses else 0.0
    reward_risk = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    if reward_risk <= 0:
        trade_rr = [float(t.reward_risk) for t in trades if t.reward_risk]
        reward_risk = float(np.mean(trade_rr)) if trade_rr else 0.0
    kelly = kelly_fraction((win_rate / 100.0) if realized_pnls else 0.0, reward_risk)
    durations = trade_durations or []

    return {
        "side": "mixed" if sleeve == "dual" else ("short" if sleeve == "short" else "long"),
        "sleeve": sleeve,
        "total_return_pct": round(float(total_return), 4),
        "max_drawdown_pct": round(float(max_drawdown) * 100, 4),
        "max_adverse_excursion": round(float(max_drawdown) * 100, 4),
        "sharpe_ratio": round(float(sharpe), 4),
        "sortino_ratio": round(float(sortino), 4),
        "trades": len(trades),
        "round_trips": len(exits),
        "win_rate": round(float(win_rate), 2),
        "win_rate_pct": round(float(win_rate), 2),
        "profit_factor": round(float(profit_factor), 4) if np.isfinite(profit_factor) else None,
        "reward_risk": round(float(reward_risk), 4),
        "kelly_fraction": kelly,
        "avg_trade_minutes": round(float(np.mean(durations)), 2) if durations else 0.0,
        "ending_equity": round(float(equity_series.iloc[-1]), 4),
        "formula_snapshot": formula_snapshot_value or {},
    }


def _infer_annualization_factor(index: pd.DatetimeIndex) -> int:
    if len(index) < 2:
        return 365
    diffs = index.to_series().diff().dropna()
    if diffs.empty:
        return 365
    seconds = diffs.median().total_seconds()
    if seconds <= 60:
        return 365 * 24 * 60
    if seconds <= 3600:
        return 365 * 24
    if seconds <= 86400:
        return 365
    return 365


def _empty_metrics() -> dict:
    return {
        "side": "long",
        "sleeve": "long",
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "max_adverse_excursion": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "trades": 0,
        "round_trips": 0,
        "win_rate": 0.0,
        "win_rate_pct": 0.0,
        "profit_factor": 0.0,
        "reward_risk": 0.0,
        "kelly_fraction": 0.0,
        "avg_trade_minutes": 0.0,
        "ending_equity": 0.0,
        "formula_snapshot": {},
    }


def _safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(result):
        return 0.0
    return result
