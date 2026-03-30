from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImportRun(Base):
    __tablename__ = "import_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False)
    kind = Column(String(64), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    owner_id = Column(String(64), nullable=True)
    source_key = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="started")
    started_at = Column(DateTime(timezone=True), default=utc_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    row_count = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source",
            "kind",
            "symbol",
            "exchange",
            "owner_id",
            "source_key",
            name="uq_import_runs_source_key",
        ),
    )
