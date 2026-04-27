from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models.paper import (
    PaperAccount,
    PaperPosition,
    PaperOrder,
    PaperSchedule,
)
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.paper_trading import PaperStepPayload, execute_paper_step
from database import get_db


router = APIRouter(prefix="/paper", tags=["Paper Trading"])


class PaperAccountCreate(BaseModel):
    name: str
    base_currency: str = "USD"
    cash_balance: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    max_position_pct: float = 1.0


class PaperAccountResponse(BaseModel):
    id: int
    name: str
    base_currency: str
    cash_balance: float
    equity: float
    last_signal: Optional[str] = None
    last_step_at: Optional[datetime] = None
    last_equity: Optional[float] = None
    equity_peak: Optional[float] = None


class PaperStepRequest(BaseModel):
    symbol: str
    exchange: str = Field(default_factory=lambda: settings.PRIMARY_EXCHANGE)
    timeframe: str = "1m"
    lookback: int = 200
    as_of: datetime | None = None
    source: str = "auto"

    strategy: str = "sma_cross"
    strategy_params: dict = Field(default_factory=dict)


class PaperPositionResponse(BaseModel):
    symbol: str
    exchange: str
    quantity: float
    avg_entry_price: float
    last_price: float
    updated_at: Optional[datetime] = None


class PaperOrderResponse(BaseModel):
    id: int
    symbol: str
    exchange: str
    side: str
    status: str
    price: float
    quantity: float
    fee: float
    strategy: Optional[str] = None
    reason: Optional[str] = None
    timestamp: Optional[datetime] = None


class PaperScheduleCreate(BaseModel):
    account_id: int
    symbol: str
    exchange: str = Field(default_factory=lambda: settings.PRIMARY_EXCHANGE)
    timeframe: str = "1m"
    lookback: int = 200
    source: str = "auto"
    strategy: str = "sma_cross"
    strategy_params: dict = Field(default_factory=dict)
    interval_seconds: int = 60
    max_drawdown_pct: Optional[float] = None
    is_active: bool = True


class PaperScheduleUpdate(BaseModel):
    is_active: Optional[bool] = None
    interval_seconds: Optional[int] = None
    max_drawdown_pct: Optional[float] = None


class PaperScheduleResponse(BaseModel):
    id: int
    account_id: int
    symbol: str
    exchange: str
    timeframe: str
    lookback: int
    source: str
    strategy: str
    strategy_params: dict
    interval_seconds: int
    max_drawdown_pct: Optional[float] = None
    is_active: bool
    disabled_reason: Optional[str] = None
    last_run_at: Optional[datetime] = None


@router.post("/accounts", response_model=PaperAccountResponse)
def create_account(
    payload: PaperAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exists = (
        db.query(PaperAccount)
        .filter(PaperAccount.user_id == current_user.id, PaperAccount.name == payload.name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Paper account name already exists.")

    account = PaperAccount(
        user_id=current_user.id,
        name=payload.name,
        base_currency=payload.base_currency,
        cash_balance=payload.cash_balance,
        fee_rate=payload.fee_rate,
        slippage_bps=payload.slippage_bps,
        max_position_pct=payload.max_position_pct,
        last_equity=payload.cash_balance,
        equity_peak=payload.cash_balance,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    return PaperAccountResponse(
        id=account.id,
        name=account.name,
        base_currency=account.base_currency,
        cash_balance=account.cash_balance,
        equity=account.cash_balance,
        last_signal=account.last_signal,
        last_step_at=account.last_step_at,
        last_equity=account.last_equity,
        equity_peak=account.equity_peak,
    )


@router.get("/accounts", response_model=list[PaperAccountResponse])
def list_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    accounts = db.query(PaperAccount).filter(PaperAccount.user_id == current_user.id).all()
    account_ids = [account.id for account in accounts]
    positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id.in_(account_ids))
        .all()
        if account_ids
        else []
    )
    positions_by_account: dict[int, list[PaperPosition]] = {}
    for position in positions:
        positions_by_account.setdefault(position.account_id, []).append(position)

    response = []
    for account in accounts:
        account_positions = positions_by_account.get(account.id, [])
        equity = account.cash_balance + sum(p.quantity * p.last_price for p in account_positions)
        response.append(
            PaperAccountResponse(
                id=account.id,
                name=account.name,
                base_currency=account.base_currency,
                cash_balance=account.cash_balance,
                equity=equity,
                last_signal=account.last_signal,
                last_step_at=account.last_step_at,
                last_equity=account.last_equity,
                equity_peak=account.equity_peak,
            )
        )
    return response


@router.get("/accounts/{account_id}", response_model=PaperAccountResponse)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = _get_owned_account(db, account_id, current_user)

    positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account_id)
        .all()
    )
    equity = account.cash_balance + sum(p.quantity * p.last_price for p in positions)

    return PaperAccountResponse(
        id=account.id,
        name=account.name,
        base_currency=account.base_currency,
        cash_balance=account.cash_balance,
        equity=equity,
        last_signal=account.last_signal,
        last_step_at=account.last_step_at,
        last_equity=account.last_equity,
        equity_peak=account.equity_peak,
    )


@router.get("/accounts/{account_id}/positions", response_model=list[PaperPositionResponse])
def list_positions(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_account(db, account_id, current_user)
    positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account_id)
        .order_by(PaperPosition.symbol.asc())
        .all()
    )
    return [
        PaperPositionResponse(
            symbol=position.symbol,
            exchange=position.exchange,
            quantity=position.quantity,
            avg_entry_price=position.avg_entry_price,
            last_price=position.last_price,
            updated_at=position.updated_at,
        )
        for position in positions
    ]


@router.get("/accounts/{account_id}/orders", response_model=list[PaperOrderResponse])
def list_orders(
    account_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_account(db, account_id, current_user)
    orders = (
        db.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .order_by(PaperOrder.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        PaperOrderResponse(
            id=order.id,
            symbol=order.symbol,
            exchange=order.exchange,
            side=order.side.value,
            status=order.status.value,
            price=order.price,
            quantity=order.quantity,
            fee=order.fee,
            strategy=order.strategy,
            reason=order.reason,
            timestamp=order.timestamp,
        )
        for order in orders
    ]


@router.post("/accounts/{account_id}/step")
def paper_step(
    account_id: int,
    payload: PaperStepRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    account = _get_owned_account(db, account_id, current_user)

    try:
        result = execute_paper_step(
            db=db,
            account=account,
            payload=PaperStepPayload(
                symbol=payload.symbol,
                exchange=payload.exchange,
                timeframe=payload.timeframe,
                lookback=payload.lookback,
                as_of=payload.as_of,
                source=payload.source,
                strategy=payload.strategy,
                strategy_params=payload.strategy_params or {},
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.get("status") == "no_data":
        raise HTTPException(status_code=404, detail="Not enough candle data to evaluate paper trade.")

    db.commit()
    return result


@router.post("/schedules", response_model=PaperScheduleResponse)
def create_schedule(
    payload: PaperScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_account(db, payload.account_id, current_user)

    schedule = PaperSchedule(
        account_id=payload.account_id,
        symbol=payload.symbol.strip().upper(),
        exchange=payload.exchange.strip().lower(),
        timeframe=payload.timeframe,
        lookback=payload.lookback,
        source=payload.source,
        strategy=payload.strategy,
        strategy_params=payload.strategy_params or {},
        interval_seconds=payload.interval_seconds,
        max_drawdown_pct=payload.max_drawdown_pct,
        is_active=payload.is_active,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return _schedule_response(schedule)


@router.get("/schedules", response_model=list[PaperScheduleResponse])
def list_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedules = (
        db.query(PaperSchedule)
        .join(PaperAccount, PaperSchedule.account_id == PaperAccount.id)
        .filter(PaperAccount.user_id == current_user.id)
        .order_by(PaperSchedule.created_at.desc())
        .all()
    )
    return [_schedule_response(schedule) for schedule in schedules]


@router.patch("/schedules/{schedule_id}", response_model=PaperScheduleResponse)
def update_schedule(
    schedule_id: int,
    payload: PaperScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = _get_owned_schedule(db, schedule_id, current_user)

    if payload.is_active is not None:
        schedule.is_active = payload.is_active
        if payload.is_active:
            schedule.disabled_reason = None
    if payload.interval_seconds is not None:
        schedule.interval_seconds = payload.interval_seconds
    if payload.max_drawdown_pct is not None:
        schedule.max_drawdown_pct = payload.max_drawdown_pct

    db.commit()
    db.refresh(schedule)
    return _schedule_response(schedule)


@router.post("/schedules/{schedule_id}/run")
def run_schedule(
    schedule_id: int,
    as_of: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = _get_owned_schedule(db, schedule_id, current_user)
    if not schedule.is_active:
        raise HTTPException(status_code=409, detail="Schedule is inactive.")

    account = _get_owned_account(db, schedule.account_id, current_user)

    result = execute_paper_step(
        db=db,
        account=account,
        payload=PaperStepPayload(
            symbol=schedule.symbol,
            exchange=schedule.exchange,
            timeframe=schedule.timeframe,
            lookback=schedule.lookback,
            as_of=as_of,
            source=schedule.source,
            strategy=schedule.strategy,
            strategy_params=schedule.strategy_params or {},
        ),
    )

    if result.get("status") == "no_data":
        raise HTTPException(status_code=404, detail="Not enough candle data to evaluate schedule.")

    schedule.last_run_at = datetime.now(timezone.utc)
    if schedule.max_drawdown_pct is not None and account.equity_peak and account.last_equity:
        if account.equity_peak > 0:
            drawdown_pct = (1 - (account.last_equity / account.equity_peak)) * 100
            if drawdown_pct >= schedule.max_drawdown_pct:
                schedule.is_active = False
                schedule.disabled_reason = f"max_drawdown {drawdown_pct:.2f}%"
    db.commit()

    return {"schedule": _schedule_response(schedule), "result": result}


def _get_owned_account(db: Session, account_id: int, current_user: User) -> PaperAccount:
    account = (
        db.query(PaperAccount)
        .filter(PaperAccount.id == account_id, PaperAccount.user_id == current_user.id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Paper account not found.")
    return account


def _get_owned_schedule(db: Session, schedule_id: int, current_user: User) -> PaperSchedule:
    schedule = (
        db.query(PaperSchedule)
        .join(PaperAccount, PaperSchedule.account_id == PaperAccount.id)
        .filter(PaperSchedule.id == schedule_id, PaperAccount.user_id == current_user.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return schedule


def _schedule_response(schedule: PaperSchedule) -> PaperScheduleResponse:
    return PaperScheduleResponse(
        id=schedule.id,
        account_id=schedule.account_id,
        symbol=schedule.symbol,
        exchange=schedule.exchange,
        timeframe=schedule.timeframe,
        lookback=schedule.lookback,
        source=schedule.source,
        strategy=schedule.strategy,
        strategy_params=schedule.strategy_params or {},
        interval_seconds=schedule.interval_seconds,
        max_drawdown_pct=schedule.max_drawdown_pct,
        is_active=bool(schedule.is_active),
        disabled_reason=schedule.disabled_reason,
        last_run_at=schedule.last_run_at,
    )
