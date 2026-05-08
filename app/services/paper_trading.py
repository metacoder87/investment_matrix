from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.execution import (
    ExecutionSettings,
    compute_buy_fill,
    compute_sell_fill,
    compute_short_cover_fill,
    compute_short_open_fill,
)
from app.backtesting.strategies import SignalAction, create_strategy
from app.models.paper import (
    PaperAccount,
    PaperOrder,
    PaperOrderSide,
    PaperOrderStatus,
    PaperPosition,
)
from app.services.market_candles import load_candles_df, parse_timeframe_seconds


@dataclass
class PaperStepPayload:
    symbol: str
    exchange: str
    timeframe: str
    lookback: int
    as_of: datetime | None
    source: str
    strategy: str
    strategy_params: dict


def execute_paper_step(
    db: Session,
    account: PaperAccount,
    payload: PaperStepPayload,
    commit: bool = False,
) -> dict[str, Any]:
    end_dt = payload.as_of or datetime.now(timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    symbol_key = payload.symbol.strip().upper()
    exchange_key = payload.exchange.strip().lower()

    bucket_seconds = parse_timeframe_seconds(payload.timeframe)
    start_dt = end_dt - timedelta(seconds=bucket_seconds * payload.lookback)

    candles = load_candles_df(
        db=db,
        exchange=exchange_key,
        symbol=symbol_key,
        start=start_dt,
        end=end_dt,
        timeframe=payload.timeframe,
        source=payload.source,
    )

    if candles.df.empty or len(candles.df) < 2:
        return {"status": "no_data"}

    strategy = create_strategy(payload.strategy, payload.strategy_params)
    prepared = strategy.prepare(candles.df.copy())
    signals = strategy.generate_signals(prepared)
    signal = signals[-1]

    price = float(prepared["close"].iloc[-1])
    positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account.id)
        .all()
    )
    long_position = next(
        (pos for pos in positions if pos.symbol == symbol_key and pos.exchange == exchange_key and (pos.side or "long") == "long"),
        None,
    )
    short_position = next(
        (pos for pos in positions if pos.symbol == symbol_key and pos.exchange == exchange_key and (pos.side or "long") == "short"),
        None,
    )

    equity = _account_equity(positions, float(account.cash_balance or 0.0), symbol_key, price)

    execution = ExecutionSettings(
        fee_rate=account.fee_rate,
        slippage_bps=account.slippage_bps,
        max_position_pct=account.max_position_pct,
    )

    order_payload = None
    position = long_position or short_position
    if signal == SignalAction.BUY and (long_position is None or long_position.quantity <= 0):
        fill = compute_buy_fill(account.cash_balance, equity, price, execution)
        if fill:
            account.cash_balance += fill.cash_delta
            if long_position is None:
                position = PaperPosition(
                    account_id=account.id,
                    exchange=exchange_key,
                    symbol=symbol_key,
                    side="long",
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    last_price=price,
                )
                db.add(position)
                positions.append(position)
            else:
                long_position.quantity = fill.quantity
                long_position.avg_entry_price = fill.price
                long_position.last_price = price
                position = long_position

            order = PaperOrder(
                account_id=account.id,
                exchange=exchange_key,
                symbol=symbol_key,
                side=PaperOrderSide.BUY,
                status=PaperOrderStatus.FILLED,
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                strategy=strategy.name,
                reason="signal",
            )
            db.add(order)
            db.flush()
            order_payload = _order_payload(order)
        else:
            order_payload = {"status": PaperOrderStatus.REJECTED.value, "reason": "insufficient_cash"}

    elif signal == SignalAction.SELL and long_position is not None and long_position.quantity > 0:
        position = long_position
        fill = compute_sell_fill(long_position.quantity, price, execution)
        if fill:
            account.cash_balance += fill.cash_delta
            order = PaperOrder(
                account_id=account.id,
                exchange=exchange_key,
                symbol=symbol_key,
                side=PaperOrderSide.SELL,
                status=PaperOrderStatus.FILLED,
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                strategy=strategy.name,
                reason="signal",
            )
            db.add(order)
            db.flush()
            order_payload = _order_payload(order)
            long_position.quantity = 0.0
            long_position.last_price = price
        else:
            order_payload = {"status": PaperOrderStatus.REJECTED.value, "reason": "invalid_fill"}

    elif signal == SignalAction.SHORT and (short_position is None or short_position.quantity <= 0):
        fill = compute_short_open_fill(account.cash_balance, equity, price, execution)
        if fill:
            account.cash_balance += fill.cash_delta
            if short_position is None:
                position = PaperPosition(
                    account_id=account.id,
                    exchange=exchange_key,
                    symbol=symbol_key,
                    side="short",
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    last_price=price,
                    reserved_collateral=fill.notional,
                )
                db.add(position)
                positions.append(position)
            else:
                short_position.quantity = fill.quantity
                short_position.avg_entry_price = fill.price
                short_position.last_price = price
                short_position.reserved_collateral = fill.notional
                position = short_position

            order = PaperOrder(
                account_id=account.id,
                exchange=exchange_key,
                symbol=symbol_key,
                side=PaperOrderSide.SHORT,
                status=PaperOrderStatus.FILLED,
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                strategy=strategy.name,
                reason="signal",
            )
            db.add(order)
            db.flush()
            order_payload = _order_payload(order)
        else:
            order_payload = {"status": PaperOrderStatus.REJECTED.value, "reason": "insufficient_cash"}

    elif signal == SignalAction.COVER and short_position is not None and short_position.quantity > 0:
        position = short_position
        fill = compute_short_cover_fill(
            short_position.quantity,
            short_position.avg_entry_price,
            short_position.reserved_collateral or 0.0,
            price,
            execution,
        )
        if fill:
            account.cash_balance += fill.cash_delta
            order = PaperOrder(
                account_id=account.id,
                exchange=exchange_key,
                symbol=symbol_key,
                side=PaperOrderSide.COVER,
                status=PaperOrderStatus.FILLED,
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                strategy=strategy.name,
                reason="signal",
            )
            db.add(order)
            db.flush()
            order_payload = _order_payload(order)
            short_position.quantity = 0.0
            short_position.last_price = price
            short_position.reserved_collateral = 0.0
        else:
            order_payload = {"status": PaperOrderStatus.REJECTED.value, "reason": "invalid_cover_fill"}

    if position is not None and position.quantity <= 0:
        if position in positions:
            positions.remove(position)
        db.delete(position)
        position_payload = None
    elif position is not None:
        position.last_price = price
        position_payload = _position_payload(position)
    else:
        position_payload = None

    equity_total = _account_equity(positions, float(account.cash_balance or 0.0), symbol_key, price)

    account.last_signal = signal.value
    account.last_step_at = end_dt
    account.last_equity = equity_total
    if account.equity_peak is None or account.equity_peak <= 0:
        account.equity_peak = equity_total
    else:
        account.equity_peak = max(account.equity_peak, equity_total)

    if commit:
        db.commit()

    return {
        "status": "ok",
        "account_id": account.id,
        "symbol": symbol_key,
        "exchange": exchange_key,
        "signal": signal.value,
        "price": price,
        "order": order_payload,
        "position": position_payload,
        "cash_balance": account.cash_balance,
        "equity": equity_total,
    }


def _order_payload(order: PaperOrder) -> dict[str, Any]:
    return {
        "id": order.id,
        "side": order.side.value,
        "status": order.status.value,
        "price": order.price,
        "quantity": order.quantity,
        "fee": order.fee,
        "strategy": order.strategy,
        "reason": order.reason,
        "timestamp": order.timestamp.isoformat() if order.timestamp else None,
    }


def _position_payload(position: PaperPosition) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "exchange": position.exchange,
        "side": position.side or "long",
        "quantity": position.quantity,
        "avg_entry_price": position.avg_entry_price,
        "last_price": position.last_price,
        "reserved_collateral": position.reserved_collateral or 0.0,
        "take_profit": position.take_profit,
        "stop_loss": position.stop_loss,
        "updated_at": position.updated_at.isoformat() if position.updated_at else None,
    }


def _account_equity(positions: list[PaperPosition], cash: float, symbol_key: str, mark_price: float) -> float:
    equity = cash
    for pos in positions:
        price = mark_price if pos.symbol == symbol_key else float(pos.last_price or 0.0)
        qty = float(pos.quantity or 0.0)
        if (pos.side or "long") == "short":
            entry = float(pos.avg_entry_price or 0.0)
            equity += float(pos.reserved_collateral or 0.0) + (entry - price) * qty
        else:
            equity += qty * price
    return equity
