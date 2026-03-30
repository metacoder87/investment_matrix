from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from app.services.imports.types import TickRecord


class BaseTickImporter(ABC):
    """Base class for streaming tick imports."""

    def __init__(self, *, symbol: str, exchange: str) -> None:
        self.symbol = symbol
        self.exchange = exchange

    @abstractmethod
    def iter_ticks(self) -> Iterable[TickRecord]:
        """Yield TickRecord items in time order."""
        raise NotImplementedError
