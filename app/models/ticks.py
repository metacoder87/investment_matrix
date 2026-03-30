from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from database import Base


class Asset(Base):
    """
    Registry of tradable assets for tick storage.

    Symbols are stored in canonical BASE-QUOTE form (e.g. BTC-USD).
    Exchange is stored separately to allow the same symbol on multiple venues.
    """

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    base = Column(String(20), nullable=False)
    quote = Column(String(20), nullable=False)
    tick_precision = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=False, default=True)

    ticks = relationship("Tick", back_populates="asset", cascade="all, delete-orphan")
    ticks_focus = relationship("TickFocus", back_populates="asset", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_assets_exchange_symbol"),
        Index("ix_assets_symbol", "symbol"),
        Index("ix_assets_exchange", "exchange"),
    )


class Tick(Base):
    """
    Raw tick-level trades.

    owner_id is reserved for user-scoped imports; null indicates global data.
    """

    __tablename__ = "ticks"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    side = Column(String(4), nullable=True)
    exchange_trade_id = Column(String(64), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    ingest_source = Column(String(32), nullable=True)
    is_aggregated = Column(Boolean, nullable=False, default=False)
    owner_id = Column(String(64), nullable=True)

    asset = relationship("Asset", back_populates="ticks")

    __table_args__ = (
        Index("ix_ticks_asset_time", "asset_id", "time"),
        Index("ix_ticks_trade_id", "exchange_trade_id"),
        Index(
            "ux_ticks_asset_trade_time",
            "asset_id",
            "exchange_trade_id",
            "time",
            unique=True,
            postgresql_where=text("exchange_trade_id IS NOT NULL"),
        ),
    )


class TickFocus(Base):
    """
    High-fidelity ticks around detected anomalies (no retention policy).
    """

    __tablename__ = "ticks_focus"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    side = Column(String(4), nullable=True)
    exchange_trade_id = Column(String(64), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    ingest_source = Column(String(32), nullable=True)
    focus_reason = Column(String(64), nullable=True)
    focus_score = Column(Float, nullable=True)
    owner_id = Column(String(64), nullable=True)

    asset = relationship("Asset", back_populates="ticks_focus")

    __table_args__ = (
        Index("ix_ticks_focus_asset_time", "asset_id", "time"),
        Index("ix_ticks_focus_trade_id", "exchange_trade_id"),
    )
