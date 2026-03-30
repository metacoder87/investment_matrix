from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionSettings:
    fee_rate: float
    slippage_bps: float
    max_position_pct: float
    min_trade_value: float = 10.0


@dataclass
class FillResult:
    quantity: float
    price: float
    fee: float
    notional: float
    cash_delta: float


def compute_buy_fill(cash: float, equity: float, price: float, settings: ExecutionSettings) -> FillResult | None:
    if cash <= 0 or price <= 0:
        return None

    target_value = min(cash, equity * settings.max_position_pct)
    if target_value < settings.min_trade_value:
        return None

    fill_price = price * (1 + settings.slippage_bps / 10_000)
    if fill_price <= 0:
        return None

    qty = target_value / fill_price
    fee = qty * fill_price * settings.fee_rate
    total_cost = qty * fill_price + fee

    if total_cost > cash:
        qty = cash / (fill_price * (1 + settings.fee_rate))
        if qty <= 0:
            return None
        fee = qty * fill_price * settings.fee_rate
        total_cost = qty * fill_price + fee

    if qty <= 0 or total_cost <= 0:
        return None

    return FillResult(
        quantity=qty,
        price=fill_price,
        fee=fee,
        notional=qty * fill_price,
        cash_delta=-total_cost,
    )


def compute_sell_fill(position_qty: float, price: float, settings: ExecutionSettings) -> FillResult | None:
    if position_qty <= 0 or price <= 0:
        return None

    fill_price = price * (1 - settings.slippage_bps / 10_000)
    if fill_price <= 0:
        return None

    notional = position_qty * fill_price
    fee = notional * settings.fee_rate
    cash_delta = notional - fee

    return FillResult(
        quantity=position_qty,
        price=fill_price,
        fee=fee,
        notional=notional,
        cash_delta=cash_delta,
    )
