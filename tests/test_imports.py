import csv
import lzma
import struct
from datetime import datetime, timezone

from app.services.imports.binance_vision import trades_importer
from app.services.imports.csv_loader import CsvTickImporter
from app.models.ticks import Tick
from app.services.imports.dukascopy import DukascopyBi5Importer
from app.services.imports.ingest import ingest_ticks


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_csv_importer_and_ingest(tmp_path, db_session):
    path = tmp_path / "ticks.csv"
    rows = [
        {"timestamp": "1700000000000", "price": "100", "qty": "0.5"},
        {"timestamp": "1700000001000", "price": "101", "qty": "0.8"},
    ]
    _write_csv(path, rows, ["timestamp", "price", "qty"])

    importer = CsvTickImporter(
        path=path,
        symbol="BTC-USD",
        exchange="coinbase",
        mapping={"time": "timestamp", "price": "price", "volume": "qty"},
        time_unit="ms",
    )

    inserted = ingest_ticks(
        db_session,
        importer=importer,
        source="test",
        kind="csv",
        source_key=str(path),
        ingest_source="unit_test",
    )
    assert inserted == 2


def test_binance_vision_trade_mapping(tmp_path):
    path = tmp_path / "trades.csv"
    rows = [
        {
            "tradeId": "100",
            "price": "200",
            "qty": "1.2",
            "quoteQty": "240",
            "time": "1700000000000",
            "isBuyerMaker": "true",
            "isBestMatch": "true",
        }
    ]
    _write_csv(path, rows, ["tradeId", "price", "qty", "quoteQty", "time", "isBuyerMaker", "isBestMatch"])

    importer = trades_importer(path, symbol="BTC-USDT", exchange="binance")
    ticks = list(importer.iter_ticks())
    assert len(ticks) == 1
    assert ticks[0].side == "sell"
    assert ticks[0].exchange_trade_id == "100"


def test_dukascopy_bi5_parser(tmp_path):
    base_time = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    raw_records = b"".join(
        [
            struct.pack(">IIIII", 0, 100000, 99900, 1000, 1000),
            struct.pack(">IIIII", 1000, 100050, 99950, 1200, 800),
        ]
    )
    encoded = lzma.compress(raw_records)
    path = tmp_path / "sample.bi5"
    path.write_bytes(encoded)

    importer = DukascopyBi5Importer(
        path=path,
        symbol="BTCUSD",
        exchange="dukascopy",
        base_time=base_time,
        price_scale=100000,
        volume_scale=100000,
    )
    ticks = list(importer.iter_ticks())
    assert len(ticks) == 2
    assert ticks[0].time == base_time
    assert abs(ticks[0].price - 0.9995) < 1e-6


def test_dukascopy_base_time_inferred_from_filename(tmp_path):
    path = tmp_path / "BTCUSD_20240101_12h_ticks.bi5"
    path.write_bytes(b"")
    importer = DukascopyBi5Importer(
        path=path,
        symbol="BTC-USD",
        exchange="dukascopy",
    )
    assert importer.base_time == datetime(2024, 1, 1, 12, tzinfo=timezone.utc)


def test_ingest_ticks_dedupes_trade_id(tmp_path, db_session):
    path = tmp_path / "trades.csv"
    rows = [
        {
            "tradeId": "42",
            "price": "200",
            "qty": "1.2",
            "quoteQty": "240",
            "time": "1700000000000",
            "isBuyerMaker": "true",
            "isBestMatch": "true",
        },
        {
            "tradeId": "42",
            "price": "200",
            "qty": "1.2",
            "quoteQty": "240",
            "time": "1700000000000",
            "isBuyerMaker": "true",
            "isBestMatch": "true",
        },
    ]
    _write_csv(path, rows, ["tradeId", "price", "qty", "quoteQty", "time", "isBuyerMaker", "isBestMatch"])

    importer = trades_importer(path, symbol="BTC-USDT", exchange="binance")
    inserted = ingest_ticks(
        db_session,
        importer=importer,
        source="test",
        kind="trades",
        source_key=str(path),
        ingest_source="unit_test",
    )
    assert inserted == 1
    assert db_session.query(Tick).count() == 1
