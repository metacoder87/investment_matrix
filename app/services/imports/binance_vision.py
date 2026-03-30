from __future__ import annotations

from pathlib import Path

from app.services.imports.csv_loader import CsvTickImporter


def trades_importer(path: str | Path, *, symbol: str, exchange: str) -> CsvTickImporter:
    """
    Binance Vision spot trades CSV.

    Expected columns:
    tradeId,price,qty,quoteQty,time,isBuyerMaker,isBestMatch
    """
    side_map = {
        "true": "sell",
        "false": "buy",
        "True": "sell",
        "False": "buy",
        "1": "sell",
        "0": "buy",
    }
    return CsvTickImporter(
        path=path,
        symbol=symbol,
        exchange=exchange,
        mapping={
            "time": "time",
            "price": "price",
            "volume": "qty",
            "side": "isBuyerMaker",
            "trade_id": "tradeId",
        },
        time_unit="ms",
        side_map=side_map,
        is_aggregated=False,
    )


def agg_trades_importer(path: str | Path, *, symbol: str, exchange: str) -> CsvTickImporter:
    """
    Binance Vision aggTrades CSV.

    Expected columns:
    aggTradeId,price,qty,firstTradeId,lastTradeId,timestamp,isBuyerMaker,isBestMatch
    """
    side_map = {
        "true": "sell",
        "false": "buy",
        "True": "sell",
        "False": "buy",
        "1": "sell",
        "0": "buy",
    }
    return CsvTickImporter(
        path=path,
        symbol=symbol,
        exchange=exchange,
        mapping={
            "time": "timestamp",
            "price": "price",
            "volume": "qty",
            "side": "isBuyerMaker",
            "trade_id": "aggTradeId",
        },
        time_unit="ms",
        side_map=side_map,
        is_aggregated=True,
    )
