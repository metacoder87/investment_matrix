from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum as SAEnum, Boolean
from sqlalchemy.orm import relationship
import enum

from database import Base


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, enum.Enum):
    FILLED = "filled"
    OPEN = "open"
    CANCELED = "canceled"

class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"

class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_paper = Column(Boolean, default=True)
    auto_trade_enabled = Column(Boolean, default=False)
    balance_cash = Column(Float, default=0.0)

    encrypted_api_key = Column(String, nullable=True)
    encrypted_api_secret = Column(String, nullable=True)
    user = relationship("User", back_populates="portfolios")
    orders = relationship("Order", back_populates="portfolio", cascade="all, delete-orphan")
    holdings = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="portfolio", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    
    amount = Column(Float, nullable=False)
    type = Column(SAEnum(TransactionType), nullable=False)
    timestamp = Column(DateTime, default=utc_now_naive)
    description = Column(String, nullable=True)
    
    portfolio = relationship("Portfolio", back_populates="transactions")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    
    symbol = Column(String, index=True, nullable=False)   # e.g. BTC-USD
    exchange = Column(String, nullable=False)             # e.g. coinbase
    
    side = Column(SAEnum(OrderSide), nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)                # Quantity
    
    status = Column(SAEnum(OrderStatus), default=OrderStatus.FILLED)
    timestamp = Column(DateTime, default=utc_now_naive, index=True)
    
    portfolio = relationship("Portfolio", back_populates="orders")


class Holding(Base):
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    
    symbol = Column(String, index=True, nullable=False)
    exchange = Column(String, nullable=False, default="coinbase")
    quantity = Column(Float, default=0.0)
    avg_entry_price = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    portfolio = relationship("Portfolio", back_populates="holdings")
