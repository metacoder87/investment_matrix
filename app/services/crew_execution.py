from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.execution import ExecutionSettings, compute_buy_fill, compute_sell_fill
from app.models.backtest import BacktestRun
from app.models.paper import PaperAccount, PaperOrder, PaperOrderSide, PaperOrderStatus, PaperPosition
from app.models.research import AgentAuditLog, AgentGuardrailProfile, AgentRecommendation, AssetDataStatus
from app.models.user import User
from app.services.crew_trace import trace_event
from app.services.paper_trading import PaperStepPayload, execute_paper_step


def get_or_create_guardrails(db: Session, current_user: User) -> AgentGuardrailProfile:
    profile = (
        db.query(AgentGuardrailProfile)
        .filter(AgentGuardrailProfile.user_id == current_user.id)
        .first()
    )
    if profile is None:
        profile = AgentGuardrailProfile(user_id=current_user.id)
        db.add(profile)
        db.flush()
    return profile


def guardrail_payload(profile: AgentGuardrailProfile) -> dict[str, Any]:
    return {
        "autonomous_enabled": bool(profile.autonomous_enabled),
        "research_enabled": bool(getattr(profile, "research_enabled", False)),
        "trigger_monitor_enabled": bool(getattr(profile, "trigger_monitor_enabled", False)),
        "research_interval_seconds": int(getattr(profile, "research_interval_seconds", None) or 1800),
        "max_position_pct": float(profile.max_position_pct or 0.35),
        "max_daily_loss_pct": float(profile.max_daily_loss_pct or 0.10),
        "max_open_positions": int(profile.max_open_positions or 12),
        "max_trades_per_day": int(profile.max_trades_per_day or 40),
        "min_data_freshness_seconds": int(profile.min_data_freshness_seconds or 900),
        "min_backtest_return_pct": float(profile.min_backtest_return_pct or 0.0),
        "min_backtest_sharpe": float(profile.min_backtest_sharpe or 0.0),
        "bankroll_reset_drawdown_pct": float(getattr(profile, "bankroll_reset_drawdown_pct", None) or 0.95),
        "default_starting_bankroll": float(getattr(profile, "default_starting_bankroll", None) or 10_000.0),
        "trade_cadence_mode": getattr(profile, "trade_cadence_mode", None) or "aggressive_paper",
        "ai_paper_account_id": getattr(profile, "ai_paper_account_id", None),
        "allowed_symbols": profile.allowed_symbols or [],
        "model_routing": {
            "default": getattr(profile, "default_llm_model", None),
            "research": getattr(profile, "research_llm_model", None),
            "thesis": getattr(profile, "thesis_llm_model", None),
            "risk": getattr(profile, "risk_llm_model", None),
            "trade": getattr(profile, "trade_llm_model", None),
        },
    }


def recommendation_payload(row: AgentRecommendation) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_name": row.agent_name,
        "strategy_name": row.strategy_name,
        "symbol": row.symbol,
        "exchange": row.exchange,
        "action": row.action,
        "confidence": row.confidence,
        "thesis": row.thesis,
        "risk_notes": row.risk_notes,
        "source_data_timestamp": row.source_data_timestamp,
        "expires_at": row.expires_at,
        "run_id": row.run_id,
        "snapshot_id": row.snapshot_id,
        "prediction_id": row.prediction_id,
        "backtest_run_id": row.backtest_run_id,
        "paper_account_id": row.paper_account_id,
        "status": row.status,
        "execution_reason": row.execution_reason,
        "evidence": row.evidence_json or {},
        "backtest_summary": row.backtest_summary or {},
        "execution_decision": row.execution_decision,
        "model_role": getattr(row, "model_role", None),
        "llm_model": getattr(row, "llm_model", None),
        "trade_decision_model": getattr(row, "trade_decision_model", None),
        "trade_decision_status": getattr(row, "trade_decision_status", None),
        "created_at": row.created_at,
    }


def attempt_autonomous_execution(
    db: Session,
    current_user: User,
    recommendation: AgentRecommendation,
    strategy_params: dict[str, Any],
) -> None:
    profile = get_or_create_guardrails(db, current_user)
    allowed, reason = check_guardrails(db, current_user, profile, recommendation)
    if not allowed:
        recommendation.status = "rejected"
        recommendation.execution_reason = reason
        recommendation.execution_decision = reason
        audit(db, current_user, "paper_trade_blocked", {"reason": reason}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="guardrail_blocked",
            status="blocked",
            public_summary=f"{recommendation.symbol} paper trade blocked by guardrails.",
            role="Risk Manager",
            run_id=recommendation.run_id,
            recommendation_id=recommendation.id,
            snapshot_id=recommendation.snapshot_id,
            exchange=recommendation.exchange,
            symbol=recommendation.symbol,
            blocker_reason=reason,
            evidence={"action": recommendation.action, "strategy": recommendation.strategy_name},
        )
        return

    account = (
        db.query(PaperAccount)
        .filter(PaperAccount.id == recommendation.paper_account_id, PaperAccount.user_id == current_user.id)
        .first()
    )
    if not account:
        recommendation.status = "rejected"
        recommendation.execution_reason = "Paper account is required and must belong to the current user."
        recommendation.execution_decision = recommendation.execution_reason
        audit(db, current_user, "paper_trade_blocked", {"reason": recommendation.execution_reason}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="guardrail_blocked",
            status="blocked",
            public_summary=f"{recommendation.symbol} paper trade blocked because the paper account is unavailable.",
            role="Risk Manager",
            run_id=recommendation.run_id,
            recommendation_id=recommendation.id,
            snapshot_id=recommendation.snapshot_id,
            exchange=recommendation.exchange,
            symbol=recommendation.symbol,
            blocker_reason=recommendation.execution_reason,
        )
        return

    original_max_position_pct = account.max_position_pct
    account.max_position_pct = min(account.max_position_pct or 1.0, profile.max_position_pct or 0.10)
    try:
        result = execute_paper_step(
            db=db,
            account=account,
            payload=PaperStepPayload(
                symbol=recommendation.symbol,
                exchange=recommendation.exchange,
                timeframe="1m",
                lookback=200,
                as_of=None,
                source="auto",
                strategy=recommendation.strategy_name,
                strategy_params=strategy_params,
            ),
        )
    finally:
        account.max_position_pct = original_max_position_pct

    if result.get("status") == "ok" and result.get("order"):
        recommendation.status = "executed"
        recommendation.execution_reason = "Autonomous paper step executed after guardrail approval."
        recommendation.execution_decision = recommendation.execution_reason
        event_type = "paper_trade_executed"
    else:
        recommendation.status = "rejected"
        recommendation.execution_reason = result.get("status") or "Strategy did not produce an executable paper order."
        recommendation.execution_decision = recommendation.execution_reason
        event_type = "paper_trade_rejected"

    audit(db, current_user, event_type, {"result": result}, recommendation.id)
    trace_event(
        db,
        current_user,
        event_type=event_type,
        status="executed" if event_type == "paper_trade_executed" else "blocked",
        public_summary=(
            f"{recommendation.symbol} paper order executed."
            if event_type == "paper_trade_executed"
            else f"{recommendation.symbol} paper order was not executed."
        ),
        role="Portfolio Manager",
        run_id=recommendation.run_id,
        recommendation_id=recommendation.id,
        snapshot_id=recommendation.snapshot_id,
        exchange=recommendation.exchange,
        symbol=recommendation.symbol,
        rationale=recommendation.execution_reason,
        blocker_reason=None if event_type == "paper_trade_executed" else recommendation.execution_reason,
        evidence={"result": result, "strategy_params": strategy_params},
    )


def execute_price_trigger_order(
    db: Session,
    *,
    account: PaperAccount,
    side: str,
    symbol: str,
    exchange: str,
    price: float,
    strategy: str,
    reason: str,
    max_position_pct: float,
) -> dict[str, Any]:
    symbol_key = symbol.strip().upper().replace("/", "-")
    exchange_key = exchange.strip().lower()
    side_key = side.strip().lower()
    if price <= 0:
        return {"status": "rejected", "reason": "invalid_price"}

    positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account.id)
        .all()
    )
    position = next(
        (row for row in positions if row.symbol == symbol_key and row.exchange == exchange_key),
        None,
    )
    equity = float(account.cash_balance or 0.0) + sum(
        float(pos.quantity or 0.0) * (price if pos.symbol == symbol_key and pos.exchange == exchange_key else float(pos.last_price or 0.0))
        for pos in positions
    )
    execution = ExecutionSettings(
        fee_rate=float(account.fee_rate or 0.001),
        slippage_bps=float(account.slippage_bps or 5.0),
        max_position_pct=max(0.01, min(float(max_position_pct or 0.35), 1.0)),
    )

    if side_key == "buy":
        fill = compute_buy_fill(float(account.cash_balance or 0.0), equity, price, execution)
        if fill is None:
            return {"status": "rejected", "reason": "insufficient_cash"}
        previous_qty = float(position.quantity or 0.0) if position else 0.0
        previous_cost = previous_qty * float(position.avg_entry_price or 0.0) if position else 0.0
        account.cash_balance += fill.cash_delta
        if position is None:
            position = PaperPosition(
                account_id=account.id,
                exchange=exchange_key,
                symbol=symbol_key,
                quantity=fill.quantity,
                avg_entry_price=fill.price,
                last_price=price,
            )
            db.add(position)
            positions.append(position)
        else:
            position.quantity = previous_qty + fill.quantity
            position.avg_entry_price = (previous_cost + fill.notional + fill.fee) / position.quantity
            position.last_price = price
        order_side = PaperOrderSide.BUY
    elif side_key == "sell":
        if position is None or float(position.quantity or 0.0) <= 0:
            return {"status": "skipped", "reason": "no_position"}
        fill = compute_sell_fill(float(position.quantity), price, execution)
        if fill is None:
            return {"status": "rejected", "reason": "invalid_sell_fill"}
        account.cash_balance += fill.cash_delta
        position.quantity = 0.0
        position.last_price = price
        order_side = PaperOrderSide.SELL
    else:
        return {"status": "rejected", "reason": "unsupported_side"}

    order = PaperOrder(
        account_id=account.id,
        exchange=exchange_key,
        symbol=symbol_key,
        side=order_side,
        status=PaperOrderStatus.FILLED,
        price=fill.price,
        quantity=fill.quantity,
        fee=fill.fee,
        strategy=strategy,
        reason=reason[:200],
    )
    db.add(order)
    db.flush()

    if position is not None and float(position.quantity or 0.0) <= 0:
        if position in positions:
            positions.remove(position)
        db.delete(position)

    equity_total = float(account.cash_balance or 0.0) + sum(
        float(pos.quantity or 0.0) * (
            price if pos.symbol == symbol_key and pos.exchange == exchange_key else float(pos.last_price or 0.0)
        )
        for pos in positions
        if float(pos.quantity or 0.0) > 0
    )
    account.last_signal = side_key
    account.last_step_at = datetime.now(timezone.utc)
    account.last_equity = equity_total
    if not account.equity_peak or account.equity_peak <= 0:
        account.equity_peak = equity_total
    else:
        account.equity_peak = max(float(account.equity_peak), equity_total)

    return {
        "status": "ok",
        "account_id": account.id,
        "symbol": symbol_key,
        "exchange": exchange_key,
        "side": side_key,
        "price": price,
        "fill_price": fill.price,
        "quantity": fill.quantity,
        "fee": fill.fee,
        "cash_balance": account.cash_balance,
        "equity": equity_total,
        "order": {
            "id": order.id,
            "side": order.side.value,
            "status": order.status.value,
            "price": order.price,
            "quantity": order.quantity,
            "fee": order.fee,
            "strategy": order.strategy,
            "reason": order.reason,
            "timestamp": order.timestamp.isoformat() if order.timestamp else None,
        },
    }


def check_guardrails(
    db: Session,
    current_user: User,
    profile: AgentGuardrailProfile,
    recommendation: AgentRecommendation,
) -> tuple[bool, str]:
    if not profile.autonomous_enabled:
        return False, "Autonomous paper trading is disabled."
    if recommendation.action not in {"buy", "sell"}:
        return False, "Only buy/sell recommendations can execute autonomously."
    if not recommendation.backtest_run_id:
        return False, "A linked backtest is required before autonomous paper execution."
    if not recommendation.paper_account_id:
        return False, "A paper account is required before autonomous paper execution."

    allowed_symbols = profile.allowed_symbols or []
    if allowed_symbols and recommendation.symbol not in allowed_symbols:
        return False, "Symbol is not in the allowed autonomous trading universe."

    backtest = (
        db.query(BacktestRun)
        .filter(BacktestRun.id == recommendation.backtest_run_id, BacktestRun.user_id == current_user.id)
        .first()
    )
    if not backtest:
        return False, "Linked backtest was not found for the current user."

    metrics = backtest.metrics or {}
    total_return_pct = float(metrics.get("total_return_pct") or metrics.get("return_pct") or 0.0)
    sharpe = float(metrics.get("sharpe_ratio") or 0.0)
    if total_return_pct < (profile.min_backtest_return_pct or 0.0):
        return False, "Backtest return does not meet the configured guardrail."
    if sharpe < (profile.min_backtest_sharpe or 0.0):
        return False, "Backtest Sharpe ratio does not meet the configured guardrail."

    staleness_limit = profile.min_data_freshness_seconds or 900
    if getattr(profile, "trade_cadence_mode", None) == "aggressive_paper":
        staleness_limit = max(staleness_limit, 7200)

    if recommendation.source_data_timestamp:
        latest = recommendation.source_data_timestamp
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - latest).total_seconds()
        if age > staleness_limit:
            return False, f"Asset data is too stale for autonomous paper trading. Data age exceeds {int(staleness_limit/60)} minutes."
    else:
        # Fallback to AssetDataStatus if source_data_timestamp is missing
        data_status = (
            db.query(AssetDataStatus)
            .filter(AssetDataStatus.exchange == recommendation.exchange, AssetDataStatus.symbol == recommendation.symbol)
            .first()
        )
        if not data_status or data_status.status not in {"ready", "stale"}:
            return False, "Asset data is not ready for autonomous paper trading."
        if data_status.latest_candle_at:
            latest = data_status.latest_candle_at
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - latest).total_seconds()
            if age > staleness_limit:
                return False, f"Asset data is too stale for autonomous paper trading. Data age exceeds {int(staleness_limit/60)} minutes."

    open_positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == recommendation.paper_account_id, PaperPosition.quantity > 0)
        .count()
    )
    if recommendation.action == "buy" and open_positions >= (profile.max_open_positions or 12):
        return False, "Maximum open positions guardrail would be exceeded."

    start_of_day = datetime.combine(datetime.now(timezone.utc).date(), time.min).replace(tzinfo=timezone.utc)
    trades_today = (
        db.query(PaperOrder)
        .filter(PaperOrder.account_id == recommendation.paper_account_id, PaperOrder.timestamp >= start_of_day)
        .count()
    )
    if trades_today >= (profile.max_trades_per_day or 40):
        return False, "Maximum trades per day guardrail would be exceeded."

    return True, "Guardrails passed."


def audit(
    db: Session,
    current_user: User,
    event_type: str,
    payload: dict,
    recommendation_id: int | None = None,
) -> None:
    db.add(
        AgentAuditLog(
            user_id=current_user.id,
            recommendation_id=recommendation_id,
            event_type=event_type,
            payload=payload,
        )
    )
