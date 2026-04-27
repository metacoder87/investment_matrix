from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.instrument import Price
from app.models.market import MarketTrade
from app.models.paper import PaperAccount, PaperOrder, PaperOrderSide, PaperPosition
from app.models.research import (
    AgentBankrollReset,
    AgentLesson,
    AgentPortfolioSnapshot,
    AgentRecommendation,
    AgentResearchThesis,
)
from app.models.user import User
from app.services.crew_execution import audit, get_or_create_guardrails


AI_ACCOUNT_NAME = "AI Team Bankroll"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_ai_account(db: Session, current_user: User) -> PaperAccount:
    profile = get_or_create_guardrails(db, current_user)
    if profile.ai_paper_account_id:
        account = (
            db.query(PaperAccount)
            .filter(PaperAccount.id == profile.ai_paper_account_id, PaperAccount.user_id == current_user.id)
            .first()
        )
        if account:
            return account

    account = (
        db.query(PaperAccount)
        .filter(PaperAccount.user_id == current_user.id, PaperAccount.name == AI_ACCOUNT_NAME)
        .first()
    )
    if account is None:
        starting_bankroll = float(
            profile.default_starting_bankroll
            or settings.CREW_DEFAULT_STARTING_BANKROLL
            or 10_000.0
        )
        account = PaperAccount(
            user_id=current_user.id,
            name=AI_ACCOUNT_NAME,
            base_currency="USD",
            cash_balance=starting_bankroll,
            fee_rate=0.001,
            slippage_bps=5.0,
            max_position_pct=float(profile.max_position_pct or 0.35),
            last_equity=starting_bankroll,
            equity_peak=starting_bankroll,
        )
        db.add(account)
        db.flush()
        audit(
            db,
            current_user,
            "ai_bankroll_account_created",
            {"account_id": account.id, "starting_bankroll": starting_bankroll},
        )

    profile.ai_paper_account_id = account.id
    return account


def latest_price(db: Session, exchange: str, symbol: str) -> tuple[float | None, datetime | None]:
    exchange_key = exchange.strip().lower()
    symbol_key = symbol.strip().upper().replace("/", "-")
    latest_ts = (
        db.query(func.max(Price.timestamp))
        .filter(Price.exchange == exchange_key, Price.symbol == symbol_key)
        .scalar()
    )
    if latest_ts is not None:
        row = (
            db.query(Price)
            .filter(Price.exchange == exchange_key, Price.symbol == symbol_key, Price.timestamp == latest_ts)
            .first()
        )
        if row and row.close is not None:
            return float(row.close), latest_ts

    trade_ts = (
        db.query(func.max(MarketTrade.timestamp))
        .filter(MarketTrade.exchange == exchange_key, MarketTrade.symbol == symbol_key)
        .scalar()
    )
    if trade_ts is not None:
        trade = (
            db.query(MarketTrade)
            .filter(MarketTrade.exchange == exchange_key, MarketTrade.symbol == symbol_key, MarketTrade.timestamp == trade_ts)
            .first()
        )
        if trade and trade.price is not None:
            return float(trade.price), trade_ts

    return None, None


def portfolio_summary(db: Session, current_user: User) -> dict[str, Any]:
    profile = get_or_create_guardrails(db, current_user)
    account = get_or_create_ai_account(db, current_user)
    summary = _build_account_summary(db, current_user, account)
    summary["settings"] = {
        "autonomous_enabled": bool(profile.autonomous_enabled),
        "research_enabled": bool(profile.research_enabled),
        "trigger_monitor_enabled": bool(profile.trigger_monitor_enabled),
        "bot_state": _bot_state(profile),
        "primary_exchange": settings.PRIMARY_EXCHANGE.strip().lower() or "kraken",
        "global_crew_enabled": bool(settings.CREW_ENABLED),
        "global_research_enabled": bool(settings.CREW_RESEARCH_ENABLED),
        "global_trigger_monitor_enabled": bool(settings.CREW_TRIGGER_MONITOR_ENABLED),
        "research_interval_seconds": int(profile.research_interval_seconds or settings.CREW_RESEARCH_INTERVAL_SECONDS),
        "max_position_pct": float(profile.max_position_pct or 0.35),
        "max_daily_loss_pct": float(profile.max_daily_loss_pct or 0.10),
        "max_open_positions": int(profile.max_open_positions or 12),
        "max_trades_per_day": int(profile.max_trades_per_day or 40),
        "bankroll_reset_drawdown_pct": float(
            profile.bankroll_reset_drawdown_pct
            or settings.CREW_BANKROLL_RESET_DRAWDOWN_PCT
            or 0.95
        ),
        "default_starting_bankroll": float(
            profile.default_starting_bankroll
            or settings.CREW_DEFAULT_STARTING_BANKROLL
            or 10_000.0
        ),
        "ai_paper_account_id": account.id,
    }
    return summary


def _bot_state(profile) -> str:
    autonomous = bool(profile.autonomous_enabled)
    researching = bool(profile.research_enabled)
    monitoring = bool(profile.trigger_monitor_enabled)
    if autonomous and researching and monitoring:
        return "running"
    if researching and not monitoring:
        return "researching"
    if monitoring and autonomous:
        return "monitoring"
    return "paused"


def record_portfolio_snapshot(db: Session, current_user: User, account: PaperAccount | None = None) -> AgentPortfolioSnapshot:
    account = account or get_or_create_ai_account(db, current_user)
    summary = _build_account_summary(db, current_user, account)
    snapshot = AgentPortfolioSnapshot(
        user_id=current_user.id,
        account_id=account.id,
        cash_balance=summary["cash_balance"],
        invested_value=summary["invested_value"],
        equity=summary["total_equity"],
        realized_pnl=summary["realized_pnl"],
        unrealized_pnl=summary["unrealized_pnl"],
        all_time_pnl=summary["all_time_pnl"],
        current_cycle_pnl=summary["current_cycle_pnl"],
        drawdown_pct=summary["drawdown_pct"],
        exposure_pct=summary["exposure_pct"],
        open_positions=summary["open_positions"],
        reset_count=summary["reset_count"],
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def equity_curve(db: Session, current_user: User, limit: int = 500) -> list[dict[str, Any]]:
    account = get_or_create_ai_account(db, current_user)
    rows = (
        db.query(AgentPortfolioSnapshot)
        .filter(AgentPortfolioSnapshot.user_id == current_user.id, AgentPortfolioSnapshot.account_id == account.id)
        .order_by(AgentPortfolioSnapshot.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": row.created_at.isoformat() if row.created_at else None,
            "cash_balance": row.cash_balance,
            "invested_value": row.invested_value,
            "equity": row.equity,
            "drawdown_pct": row.drawdown_pct,
        }
        for row in reversed(rows)
    ]


def ai_positions(db: Session, current_user: User) -> list[dict[str, Any]]:
    account = get_or_create_ai_account(db, current_user)
    return _positions_payload(db, account)


def ai_orders(db: Session, current_user: User, limit: int = 200) -> list[dict[str, Any]]:
    account = get_or_create_ai_account(db, current_user)
    return _orders_payload(db, account, limit=limit)


def reset_bankroll(
    db: Session,
    current_user: User,
    *,
    reason: str,
    lessons: str | None = None,
) -> AgentBankrollReset:
    profile = get_or_create_guardrails(db, current_user)
    account = get_or_create_ai_account(db, current_user)
    summary = _build_account_summary(db, current_user, account)
    starting_bankroll = float(
        profile.default_starting_bankroll
        or settings.CREW_DEFAULT_STARTING_BANKROLL
        or 10_000.0
    )
    reset_number = (
        db.query(AgentBankrollReset)
        .filter(AgentBankrollReset.user_id == current_user.id, AgentBankrollReset.account_id == account.id)
        .count()
        + 1
    )
    lesson_text = lessons or (
        f"Bankroll reset #{reset_number} after {summary['drawdown_pct']:.2f}% drawdown. "
        "Future research should reduce exposure when live triggers cluster in the same direction."
    )
    reset = AgentBankrollReset(
        user_id=current_user.id,
        account_id=account.id,
        reset_number=reset_number,
        starting_bankroll=starting_bankroll,
        equity_before_reset=summary["total_equity"],
        cash_before_reset=summary["cash_balance"],
        invested_before_reset=summary["invested_value"],
        drawdown_pct=summary["drawdown_pct"],
        realized_pnl=summary["total_equity"] - starting_bankroll,
        reason=reason,
        lessons=lesson_text,
    )
    db.add(reset)

    for position in (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account.id)
        .all()
    ):
        db.delete(position)

    (
        db.query(AgentResearchThesis)
        .filter(
            AgentResearchThesis.user_id == current_user.id,
            AgentResearchThesis.account_id == account.id,
            AgentResearchThesis.status.in_(("active", "entry_triggered")),
        )
        .update({"status": "cancelled", "closed_at": utc_now()}, synchronize_session=False)
    )

    account.cash_balance = starting_bankroll
    account.last_equity = starting_bankroll
    account.equity_peak = starting_bankroll
    account.last_signal = "reset"
    account.last_step_at = utc_now()

    lesson = AgentLesson(
        user_id=current_user.id,
        account_id=account.id,
        outcome="bankroll_reset",
        return_pct=((summary["total_equity"] / starting_bankroll) - 1.0) * 100 if starting_bankroll else None,
        lesson=lesson_text,
    )
    db.add(lesson)
    db.flush()
    audit(
        db,
        current_user,
        "bankroll_reset",
        {
            "account_id": account.id,
            "reset_number": reset_number,
            "equity_before_reset": summary["total_equity"],
            "drawdown_pct": summary["drawdown_pct"],
            "starting_bankroll": starting_bankroll,
            "reason": reason,
        },
    )
    record_portfolio_snapshot(db, current_user, account)
    return reset


def maybe_reset_bankroll(db: Session, current_user: User) -> AgentBankrollReset | None:
    profile = get_or_create_guardrails(db, current_user)
    account = get_or_create_ai_account(db, current_user)
    summary = _build_account_summary(db, current_user, account)
    threshold = float(
        profile.bankroll_reset_drawdown_pct
        or settings.CREW_BANKROLL_RESET_DRAWDOWN_PCT
        or 0.95
    )
    if summary["drawdown_pct"] <= -(threshold * 100):
        return reset_bankroll(
            db,
            current_user,
            reason=f"Automatic reset after drawdown reached {abs(summary['drawdown_pct']):.2f}%.",
        )
    return None


def bankroll_resets(db: Session, current_user: User, limit: int = 100) -> list[dict[str, Any]]:
    account = get_or_create_ai_account(db, current_user)
    rows = (
        db.query(AgentBankrollReset)
        .filter(AgentBankrollReset.user_id == current_user.id, AgentBankrollReset.account_id == account.id)
        .order_by(AgentBankrollReset.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_reset_payload(row) for row in rows]


def lessons(db: Session, current_user: User, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        db.query(AgentLesson)
        .filter(AgentLesson.user_id == current_user.id)
        .order_by(AgentLesson.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_lesson_payload(row) for row in rows]


def recent_lessons_for_prompt(db: Session, current_user: User, limit: int = 12) -> list[dict[str, Any]]:
    return lessons(db, current_user, limit=limit)


def strategy_performance(db: Session, current_user: User) -> list[dict[str, Any]]:
    rows = (
        db.query(AgentRecommendation)
        .filter(AgentRecommendation.user_id == current_user.id)
        .order_by(AgentRecommendation.created_at.asc())
        .all()
    )
    lessons_by_strategy: dict[str, list[AgentLesson]] = {}
    for lesson in db.query(AgentLesson).filter(AgentLesson.user_id == current_user.id).all():
        if lesson.strategy_name:
            lessons_by_strategy.setdefault(lesson.strategy_name, []).append(lesson)

    stats: dict[str, dict[str, Any]] = {}
    for rec in rows:
        key = rec.strategy_name or "unknown"
        item = stats.setdefault(
            key,
            {
                "strategy_name": key,
                "recommendations": 0,
                "executed": 0,
                "blocked": 0,
                "wins": 0,
                "losses": 0,
                "avg_return_pct": 0.0,
                "success_rate_pct": 0.0,
                "last_used_at": None,
            },
        )
        item["recommendations"] += 1
        if rec.status == "executed":
            item["executed"] += 1
        elif rec.status in {"rejected", "blocked"}:
            item["blocked"] += 1
        item["last_used_at"] = rec.created_at.isoformat() if rec.created_at else item["last_used_at"]

    for key, item in stats.items():
        returns = [
            lesson.return_pct
            for lesson in lessons_by_strategy.get(key, [])
            if lesson.return_pct is not None and lesson.outcome in {"take_profit", "stop_loss", "paper_sell", "win", "loss"}
        ]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value <= 0]
        item["wins"] = len(wins)
        item["losses"] = len(losses)
        item["avg_return_pct"] = sum(returns) / len(returns) if returns else 0.0
        item["success_rate_pct"] = (len(wins) / len(returns) * 100) if returns else 0.0

    return sorted(stats.values(), key=lambda item: item["last_used_at"] or "", reverse=True)


def _build_account_summary(db: Session, current_user: User, account: PaperAccount) -> dict[str, Any]:
    positions = _positions_payload(db, account)
    invested = sum(float(position["market_value"]) for position in positions)
    unrealized = sum(float(position["unrealized_pnl"]) for position in positions)
    cash = float(account.cash_balance or 0.0)
    equity = cash + invested

    if not account.equity_peak or account.equity_peak <= 0:
        account.equity_peak = equity
    else:
        account.equity_peak = max(float(account.equity_peak), equity)
    account.last_equity = equity

    peak = float(account.equity_peak or equity or 0.0)
    drawdown_pct = ((equity / peak) - 1.0) * 100 if peak > 0 else 0.0
    exposure_pct = (invested / equity) * 100 if equity > 0 else 0.0
    reset_count = (
        db.query(AgentBankrollReset)
        .filter(AgentBankrollReset.user_id == current_user.id, AgentBankrollReset.account_id == account.id)
        .count()
    )
    last_reset = (
        db.query(AgentBankrollReset)
        .filter(AgentBankrollReset.user_id == current_user.id, AgentBankrollReset.account_id == account.id)
        .order_by(AgentBankrollReset.created_at.desc())
        .first()
    )
    profile = get_or_create_guardrails(db, current_user)
    starting_bankroll = float(
        profile.default_starting_bankroll
        or settings.CREW_DEFAULT_STARTING_BANKROLL
        or 10_000.0
    )
    realized_pnl = _realized_pnl_from_orders(db, account)
    reset_realized = (
        db.query(func.coalesce(func.sum(AgentBankrollReset.realized_pnl), 0.0))
        .filter(AgentBankrollReset.user_id == current_user.id, AgentBankrollReset.account_id == account.id)
        .scalar()
        or 0.0
    )
    current_cycle_pnl = equity - starting_bankroll
    all_time_pnl = float(reset_realized) + current_cycle_pnl

    last_reset_at = last_reset.created_at if last_reset else None
    seconds_since_last_reset = None
    if last_reset_at:
        last_dt = last_reset_at.replace(tzinfo=timezone.utc) if last_reset_at.tzinfo is None else last_reset_at
        seconds_since_last_reset = int((utc_now() - last_dt).total_seconds())

    return {
        "account_id": account.id,
        "account_name": account.name,
        "base_currency": account.base_currency,
        "cash_balance": cash,
        "available_bankroll": cash,
        "invested_value": invested,
        "total_equity": equity,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized,
        "all_time_pnl": all_time_pnl,
        "current_cycle_pnl": current_cycle_pnl,
        "drawdown_pct": drawdown_pct,
        "exposure_pct": exposure_pct,
        "open_positions": len(positions),
        "reset_count": reset_count,
        "last_reset_at": last_reset_at.isoformat() if last_reset_at else None,
        "seconds_since_last_reset": seconds_since_last_reset,
        "positions": positions,
        "recent_orders": _orders_payload(db, account, limit=25),
    }


def _positions_payload(db: Session, account: PaperAccount) -> list[dict[str, Any]]:
    rows = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account.id, PaperPosition.quantity > 0)
        .order_by(PaperPosition.symbol.asc())
        .all()
    )
    payload = []
    for row in rows:
        mark, mark_ts = latest_price(db, row.exchange, row.symbol)
        last_price = float(mark if mark is not None else row.last_price or 0.0)
        row.last_price = last_price
        quantity = float(row.quantity or 0.0)
        avg_entry = float(row.avg_entry_price or 0.0)
        market_value = quantity * last_price
        cost_basis = quantity * avg_entry
        unrealized = market_value - cost_basis
        return_pct = ((last_price / avg_entry) - 1.0) * 100 if avg_entry > 0 else 0.0
        payload.append(
            {
                "id": row.id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "quantity": quantity,
                "avg_entry_price": avg_entry,
                "last_price": last_price,
                "latest_price_timestamp": mark_ts.isoformat() if mark_ts else None,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "unrealized_pnl": unrealized,
                "return_pct": return_pct,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return payload


def _orders_payload(db: Session, account: PaperAccount, limit: int) -> list[dict[str, Any]]:
    rows = (
        db.query(PaperOrder)
        .filter(PaperOrder.account_id == account.id)
        .order_by(PaperOrder.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "symbol": row.symbol,
            "exchange": row.exchange,
            "side": row.side.value if hasattr(row.side, "value") else str(row.side),
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "price": row.price,
            "quantity": row.quantity,
            "fee": row.fee,
            "strategy": row.strategy,
            "reason": row.reason,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }
        for row in rows
    ]


def _realized_pnl_from_orders(db: Session, account: PaperAccount) -> float:
    orders = (
        db.query(PaperOrder)
        .filter(PaperOrder.account_id == account.id)
        .order_by(PaperOrder.timestamp.asc())
        .all()
    )
    lots: dict[tuple[str, str], dict[str, float]] = {}
    realized = 0.0
    for order in orders:
        key = (order.exchange, order.symbol)
        side = order.side.value if hasattr(order.side, "value") else str(order.side)
        qty = float(order.quantity or 0.0)
        price = float(order.price or 0.0)
        fee = float(order.fee or 0.0)
        state = lots.setdefault(key, {"qty": 0.0, "avg": 0.0})
        if side == PaperOrderSide.BUY.value:
            total_cost = state["qty"] * state["avg"] + qty * price + fee
            state["qty"] += qty
            state["avg"] = total_cost / state["qty"] if state["qty"] > 0 else 0.0
        elif side == PaperOrderSide.SELL.value and state["qty"] > 0:
            sell_qty = min(qty, state["qty"])
            realized += sell_qty * (price - state["avg"]) - fee
            state["qty"] -= sell_qty
            if state["qty"] <= 0:
                state["avg"] = 0.0
    return realized


def _reset_payload(row: AgentBankrollReset) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "reset_number": row.reset_number,
        "starting_bankroll": row.starting_bankroll,
        "equity_before_reset": row.equity_before_reset,
        "cash_before_reset": row.cash_before_reset,
        "invested_before_reset": row.invested_before_reset,
        "drawdown_pct": row.drawdown_pct,
        "realized_pnl": row.realized_pnl,
        "reason": row.reason,
        "lessons": row.lessons,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _lesson_payload(row: AgentLesson) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "thesis_id": row.thesis_id,
        "recommendation_id": row.recommendation_id,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "outcome": row.outcome,
        "return_pct": row.return_pct,
        "confidence": row.confidence,
        "lesson": row.lesson,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
