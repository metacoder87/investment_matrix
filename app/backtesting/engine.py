from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.backtesting.execution import ExecutionSettings, compute_buy_fill, compute_sell_fill
from app.backtesting.strategies import SignalAction, Strategy


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

        data = df.copy()
        if "timestamp" not in data.columns:
            raise ValueError("DataFrame must include a timestamp column")
        data = data.sort_values("timestamp").reset_index(drop=True)

        data = strategy.prepare(data)
        signals = strategy.generate_signals(data)
        if len(signals) != len(data):
            raise ValueError("Signals length mismatch with data length")

        cash = self.initial_cash
        position_qty = 0.0
        entry_cost = None
        entry_price = None

        equity_curve: list[dict] = []
        trades: list[TradeRecord] = []
        realized_pnls: list[float] = []

        for idx, row in data.iterrows():
            ts = _normalize_ts(row["timestamp"])
            price = float(row["close"])
            signal = signals[idx]

            if signal == SignalAction.BUY and position_qty <= 0:
                equity = cash + position_qty * price
                fill = compute_buy_fill(cash, equity, price, self.execution)
                if fill:
                    cash += fill.cash_delta
                    position_qty += fill.quantity
                    entry_cost = fill.notional + fill.fee
                    entry_price = fill.price
                    trades.append(
                        TradeRecord(
                            timestamp=ts,
                            side=SignalAction.BUY.value,
                            price=fill.price,
                            quantity=fill.quantity,
                            fee=fill.fee,
                            cash_balance=cash,
                            equity=cash + position_qty * price,
                            reason=strategy.name,
                        )
                    )

            elif signal == SignalAction.SELL and position_qty > 0:
                fill = compute_sell_fill(position_qty, price, self.execution)
                if fill:
                    cash += fill.cash_delta
                    if entry_cost is None:
                        pnl = None
                    else:
                        pnl = fill.notional - fill.fee - entry_cost
                        realized_pnls.append(pnl)
                    position_qty = 0.0
                    entry_cost = None
                    entry_price = None
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
                            reason=strategy.name,
                        )
                    )

            equity = cash + position_qty * price
            equity_curve.append(
                {
                    "timestamp": _ensure_iso(ts),
                    "equity": equity,
                    "cash": cash,
                    "position_qty": position_qty,
                    "entry_price": entry_price,
                }
            )

        metrics = _compute_metrics(equity_curve, trades, realized_pnls, self.initial_cash)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)


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

    sells = [t for t in trades if t.side == SignalAction.SELL.value]
    wins = [pnl for pnl in realized_pnls if pnl > 0]
    losses = [pnl for pnl in realized_pnls if pnl <= 0]
    win_rate = (len(wins) / len(realized_pnls)) * 100 if realized_pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else float("inf") if wins else 0.0

    return {
        "total_return_pct": round(float(total_return), 4),
        "max_drawdown_pct": round(float(max_drawdown) * 100, 4),
        "sharpe_ratio": round(float(sharpe), 4),
        "trades": len(trades),
        "round_trips": len(sells),
        "win_rate_pct": round(float(win_rate), 2),
        "profit_factor": round(float(profit_factor), 4) if np.isfinite(profit_factor) else None,
        "ending_equity": round(float(equity_series.iloc[-1]), 4),
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
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0,
        "trades": 0,
        "round_trips": 0,
        "win_rate_pct": 0.0,
        "profit_factor": 0.0,
        "ending_equity": 0.0,
    }
