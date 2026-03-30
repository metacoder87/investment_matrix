from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TickRecord:
    time: datetime
    price: float
    volume: float
    side: str | None = None
    exchange_trade_id: str | None = None
    is_aggregated: bool = False
