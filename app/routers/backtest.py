from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.backtesting.engine import BacktestEngine
from app.backtesting.strategies import create_strategy, list_strategies
from app.backtesting.walkforward import run_walk_forward
from app.models.backtest import BacktestRun, BacktestTrade, BacktestReport
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.market_candles import load_candles_df
from database import get_db


router = APIRouter(prefix="/backtests", tags=["Backtesting"])


class BacktestRequest(BaseModel):
    symbol: str
    exchange: str = "coinbase"
    start: datetime
    end: datetime
    timeframe: str = "1m"
    source: str = "auto"

    name: str | None = None
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    max_position_pct: float = 1.0

    strategy: str = "sma_cross"
    strategy_params: dict = Field(default_factory=dict)

    include_trades: bool = True
    include_equity: bool = False


class BacktestResponse(BaseModel):
    run_id: int
    metrics: dict[str, Any]
    source: str
    requested_bucket_seconds: int
    bucket_seconds: int
    trades: list[dict] | None = None
    equity_curve: list[dict] | None = None


class WalkForwardRequest(BaseModel):
    symbol: str
    exchange: str = "coinbase"
    start: datetime
    end: datetime
    timeframe: str = "1m"
    source: str = "auto"

    name: str | None = None
    train_window: int = 300
    test_window: int = 100
    step_window: int | None = None

    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    max_position_pct: float = 1.0

    strategy: str = "sma_cross"
    strategy_params: dict = Field(default_factory=dict)
    baseline_strategies: list[str] = Field(default_factory=lambda: ["buy_hold", "sma_cross"])
    store_report: bool = True


class WalkForwardResponse(BaseModel):
    report_id: int | None
    summary: dict[str, Any]
    windows: list[dict[str, Any]]


@router.get("/strategies")
def get_strategies():
    return {"strategies": list_strategies()}


@router.post("/", response_model=BacktestResponse)
def run_backtest(
    payload: BacktestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        candles = load_candles_df(
            db=db,
            exchange=payload.exchange,
            symbol=payload.symbol,
            start=payload.start,
            end=payload.end,
            timeframe=payload.timeframe,
            source=payload.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if candles.df.empty:
        raise HTTPException(status_code=404, detail="No candle data available for backtest range.")

    try:
        strategy = create_strategy(payload.strategy, payload.strategy_params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = BacktestEngine(
        initial_cash=payload.initial_cash,
        fee_rate=payload.fee_rate,
        slippage_bps=payload.slippage_bps,
        max_position_pct=payload.max_position_pct,
    )
    result = engine.run(candles.df, strategy)

    name = payload.name or f"{payload.strategy}:{payload.symbol}:{payload.start.date().isoformat()}"
    run = BacktestRun(
        user_id=current_user.id,
        name=name,
        symbol=payload.symbol.strip().upper(),
        exchange=payload.exchange.strip().lower(),
        timeframe=payload.timeframe,
        start=payload.start,
        end=payload.end,
        initial_cash=payload.initial_cash,
        fee_rate=payload.fee_rate,
        slippage_bps=payload.slippage_bps,
        max_position_pct=payload.max_position_pct,
        strategy=strategy.name,
        strategy_params=payload.strategy_params or {},
        metrics=result.metrics,
        equity_curve=result.equity_curve if payload.include_equity else [],
    )
    db.add(run)
    db.flush()

    for trade in result.trades:
        db.add(
            BacktestTrade(
                run_id=run.id,
                timestamp=trade.timestamp,
                side=trade.side,
                price=trade.price,
                quantity=trade.quantity,
                fee=trade.fee,
                cash_balance=trade.cash_balance,
                equity=trade.equity,
                pnl=trade.pnl,
                reason=trade.reason,
            )
        )

    db.commit()

    trades_payload = None
    if payload.include_trades:
        trades_payload = [
            {
                "timestamp": trade.timestamp.isoformat(),
                "side": trade.side,
                "price": trade.price,
                "quantity": trade.quantity,
                "fee": trade.fee,
                "cash_balance": trade.cash_balance,
                "equity": trade.equity,
                "pnl": trade.pnl,
                "reason": trade.reason,
            }
            for trade in result.trades
        ]

    equity_payload = result.equity_curve if payload.include_equity else None

    return BacktestResponse(
        run_id=run.id,
        metrics=result.metrics,
        source=candles.source,
        requested_bucket_seconds=candles.requested_bucket_seconds,
        bucket_seconds=candles.bucket_seconds,
        trades=trades_payload,
        equity_curve=equity_payload,
    )


@router.post("/walk-forward", response_model=WalkForwardResponse)
def run_walk_forward_backtest(
    payload: WalkForwardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        candles = load_candles_df(
            db=db,
            exchange=payload.exchange,
            symbol=payload.symbol,
            start=payload.start,
            end=payload.end,
            timeframe=payload.timeframe,
            source=payload.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if candles.df.empty:
        raise HTTPException(status_code=404, detail="No candle data available for walk-forward range.")

    try:
        strategy = create_strategy(payload.strategy, payload.strategy_params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(candles.df) < payload.train_window + payload.test_window:
        raise HTTPException(status_code=400, detail="Not enough data for train/test windows.")

    wf = run_walk_forward(
        df=candles.df,
        strategy=strategy,
        train_window=payload.train_window,
        test_window=payload.test_window,
        step_window=payload.step_window,
        initial_cash=payload.initial_cash,
        fee_rate=payload.fee_rate,
        slippage_bps=payload.slippage_bps,
        max_position_pct=payload.max_position_pct,
        baseline_strategies=payload.baseline_strategies,
    )

    report_id = None
    if payload.store_report:
        name = payload.name or f"walk_forward:{payload.strategy}:{payload.symbol}:{payload.start.date().isoformat()}"
        report = BacktestReport(
            user_id=current_user.id,
            name=name,
            report_type="walk_forward",
            symbol=payload.symbol.strip().upper(),
            exchange=payload.exchange.strip().lower(),
            timeframe=payload.timeframe,
            start=payload.start,
            end=payload.end,
            config={
                "train_window": payload.train_window,
                "test_window": payload.test_window,
                "step_window": payload.step_window,
                "strategy": payload.strategy,
                "strategy_params": payload.strategy_params or {},
                "baseline_strategies": payload.baseline_strategies,
                "source": payload.source,
            },
            results={"summary": wf.summary, "windows": wf.windows},
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        report_id = report.id

    return WalkForwardResponse(report_id=report_id, summary=wf.summary, windows=wf.windows)


@router.get("/reports/{report_id}")
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = (
        db.query(BacktestReport)
        .filter(BacktestReport.id == report_id, BacktestReport.user_id == current_user.id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Backtest report not found.")
    return {
        "id": report.id,
        "name": report.name,
        "report_type": report.report_type,
        "symbol": report.symbol,
        "exchange": report.exchange,
        "timeframe": report.timeframe,
        "start": report.start.isoformat(),
        "end": report.end.isoformat(),
        "config": report.config or {},
        "results": report.results or {},
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/reports")
def list_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reports = (
        db.query(BacktestReport)
        .filter(BacktestReport.user_id == current_user.id)
        .order_by(BacktestReport.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": report.id,
            "name": report.name,
            "report_type": report.report_type,
            "symbol": report.symbol,
            "exchange": report.exchange,
            "timeframe": report.timeframe,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        }
        for report in reports
    ]


@router.get("/{run_id}", response_model=BacktestResponse)
def get_backtest(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = (
        db.query(BacktestRun)
        .filter(BacktestRun.id == run_id, BacktestRun.user_id == current_user.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found.")

    trades = (
        db.query(BacktestTrade)
        .filter(BacktestTrade.run_id == run_id)
        .order_by(BacktestTrade.timestamp.asc())
        .all()
    )

    trades_payload = [
        {
            "timestamp": trade.timestamp.isoformat(),
            "side": trade.side,
            "price": trade.price,
            "quantity": trade.quantity,
            "fee": trade.fee,
            "cash_balance": trade.cash_balance,
            "equity": trade.equity,
            "pnl": trade.pnl,
            "reason": trade.reason,
        }
        for trade in trades
    ]

    return BacktestResponse(
        run_id=run.id,
        metrics=run.metrics or {},
        source="stored",
        requested_bucket_seconds=0,
        bucket_seconds=0,
        trades=trades_payload,
        equity_curve=run.equity_curve or [],
    )
