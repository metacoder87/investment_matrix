from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Enum as SAEnum, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
import enum

from database import Base


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PaperOrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"


class PaperOrderStatus(str, enum.Enum):
    FILLED = "filled"
    REJECTED = "rejected"
    SKIPPED = "skipped"


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_paper_accounts_user_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(100), index=True, nullable=False)
    base_currency = Column(String(10), default="USD")
    cash_balance = Column(Float, default=0.0)

    fee_rate = Column(Float, default=0.001)
    slippage_bps = Column(Float, default=5.0)
    max_position_pct = Column(Float, default=1.0)

    last_equity = Column(Float, default=0.0)
    equity_peak = Column(Float, default=0.0)
    last_signal = Column(String(20), nullable=True)
    last_step_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    positions = relationship("PaperPosition", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("PaperOrder", back_populates="account", cascade="all, delete-orphan")
    schedules = relationship("PaperSchedule", back_populates="account", cascade="all, delete-orphan")


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(20), nullable=False, default="long")
    quantity = Column(Float, default=0.0)
    avg_entry_price = Column(Float, default=0.0)
    last_price = Column(Float, default=0.0)
    reserved_collateral = Column(Float, default=0.0)
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    trailing_peak = Column(Float, nullable=True)
    trailing_trough = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    account = relationship("PaperAccount", back_populates="positions")


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)

    side = Column(SAEnum(PaperOrderSide, values_callable=_enum_values), nullable=False)
    status = Column(SAEnum(PaperOrderStatus, values_callable=_enum_values), default=PaperOrderStatus.FILLED)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)

    strategy = Column(String(50), nullable=True)
    reason = Column(String(200), nullable=True)

    timestamp = Column(DateTime, default=utc_now_naive, index=True)

    account = relationship("PaperAccount", back_populates="orders")


class PaperSchedule(Base):
    __tablename__ = "paper_schedules"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False, index=True)

    exchange = Column(String(20), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, default="1m")
    lookback = Column(Integer, default=200)
    source = Column(String(20), default="auto")

    strategy = Column(String(50), nullable=False)
    strategy_params = Column(JSON, default=dict)

    interval_seconds = Column(Integer, default=60)
    max_drawdown_pct = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    disabled_reason = Column(String(200), nullable=True)
    last_run_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    account = relationship("PaperAccount", back_populates="schedules")
