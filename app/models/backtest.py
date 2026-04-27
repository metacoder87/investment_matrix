from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    start = Column(DateTime(timezone=True), nullable=False)
    end = Column(DateTime(timezone=True), nullable=False)

    initial_cash = Column(Float, nullable=False)
    fee_rate = Column(Float, nullable=False)
    slippage_bps = Column(Float, nullable=False)
    max_position_pct = Column(Float, nullable=False)

    strategy = Column(String(50), nullable=False)
    strategy_params = Column(JSON, default=dict)

    metrics = Column(JSON, default=dict)
    equity_curve = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trades = relationship("BacktestTrade", back_populates="run", cascade="all, delete-orphan")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    side = Column(String(4), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)

    cash_balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    pnl = Column(Float, nullable=True)
    reason = Column(String(100), nullable=True)

    run = relationship("BacktestRun", back_populates="trades")


class BacktestReport(Base):
    __tablename__ = "backtest_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    report_type = Column(String(50), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    start = Column(DateTime(timezone=True), nullable=False)
    end = Column(DateTime(timezone=True), nullable=False)

    config = Column(JSON, default=dict)
    results = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
