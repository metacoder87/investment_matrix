from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Integer, Numeric, String

from database import Base


class MarketTrade(Base):
    __tablename__ = "market_trades"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    receipt_timestamp = Column(DateTime(timezone=True), nullable=True)
    price = Column(Numeric, nullable=False)
    amount = Column(Numeric, nullable=False)
    side = Column(String(8), nullable=True)

    def __repr__(self):
        return f"<MarketTrade(exchange={self.exchange!r}, symbol={self.symbol!r}, price={self.price}, ts={self.timestamp})>"
