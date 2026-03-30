from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.services.imports.base import BaseTickImporter
from app.services.imports.binance_vision import agg_trades_importer, trades_importer
from app.services.imports.dukascopy import dukascopy_bi5_importer, dukascopy_csv_importer


ImporterFactory = Callable[..., BaseTickImporter]


IMPORTER_REGISTRY: dict[str, ImporterFactory] = {
    "binance_vision_trades": trades_importer,
    "binance_vision_agg_trades": agg_trades_importer,
    "dukascopy_csv": dukascopy_csv_importer,
    "dukascopy_bi5": dukascopy_bi5_importer,
}


def get_importer(
    kind: str,
    *,
    path: str | Path,
    symbol: str,
    exchange: str,
    **kwargs,
) -> BaseTickImporter:
    factory = IMPORTER_REGISTRY.get(kind)
    if factory is None:
        raise ValueError(f"Unknown importer kind: {kind}")
    return factory(path, symbol=symbol, exchange=exchange, **kwargs)
