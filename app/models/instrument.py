from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    DECIMAL,
    JSON,
    Integer,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from database import Base


class Coin(Base):
    """
    SQLAlchemy ORM model for the `coins` table.
    Stores basic information about each cryptocurrency.
    """
    __tablename__ = "coins"

    id = Column(String, primary_key=True, index=True) # From CoinGecko
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String, nullable=False)
    market_cap_rank = Column(Integer)
    image = Column(String)

    def __repr__(self):
        return f"<Coin(symbol='{self.symbol}', name='{self.name}')>"


class Price(Base):
    """
    SQLAlchemy ORM model for the `prices` table.
    Stores time-series data for crypto assets.
    """

    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(DECIMAL)
    high = Column(DECIMAL)
    low = Column(DECIMAL)
    close = Column(DECIMAL)
    volume = Column(DECIMAL)

    def __repr__(self):
        return f"<Price(symbol='{self.symbol}', close={self.close}, timestamp='{self.timestamp}')>"


class Indicator(Base):
    """
    SQLAlchemy ORM model for the `indicators` table.
    Stores calculated technical analysis indicators for each asset.
    """

    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    rsi = Column(DECIMAL)
    macd = Column(DECIMAL)
    # Additional indicators can be added as columns here

    def __repr__(self):
        return f"<Indicator(symbol='{self.symbol}', rsi={self.rsi}, timestamp='{self.timestamp}')>"


class Trade(Base):
    """
    SQLAlchemy ORM model for the `trades` table.
    Logs user-executed trades.
    """

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    action = Column(String(4), nullable=False)  # 'BUY' or 'SELL'
    qty = Column(DECIMAL, nullable=False)
    price = Column(DECIMAL, nullable=False)
    fee = Column(DECIMAL)
    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<Trade(user_id='{self.user_id}', symbol='{self.symbol}', action='{self.action}', qty={self.qty})>"


class Wallet(Base):
    """
    SQLAlchemy ORM model for the `wallets` table.
    Stores encrypted data for user wallets.
    """

    __tablename__ = "wallets"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encrypted_mnemonic = Column(Text, nullable=False)
    addresses = Column(JSON)  # e.g., {'BTC': '...', 'ETH': '...'}

    def __repr__(self):
        return f"<Wallet(user_id='{self.user_id}')>"


class NewsArticle(Base):
    """
    SQLAlchemy ORM model for the `news_articles` table.
    Stores news articles from various sources.
    """
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String)
    title = Column(String, nullable=False)
    url = Column(String, unique=True, nullable=False)
    content = Column(Text)
    published_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<NewsArticle(title='{self.title}', source='{self.source}')>"
