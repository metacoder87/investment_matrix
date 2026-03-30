from __future__ import annotations

import lzma
import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.services.imports.base import BaseTickImporter
from app.services.imports.csv_loader import CsvTickImporter
from app.services.imports.types import TickRecord


def dukascopy_csv_importer(path: str | Path, *, symbol: str, exchange: str) -> CsvTickImporter:
    """
    Dukascopy CSV ticks importer.

    Expected columns (common exports):
    timestamp,bid,ask,bid_volume,ask_volume
    """
    return CsvTickImporter(
        path=path,
        symbol=symbol,
        exchange=exchange,
        mapping={
            "time": "timestamp",
            "price": "bid",
            "volume": "bid_volume",
        },
        time_unit="ms",
        is_aggregated=False,
    )


class DukascopyBi5Importer(BaseTickImporter):
    """
    Dukascopy BI5 tick importer.

    Record format (20 bytes):
    - uint32 time (ms offset from hour start)
    - int32 ask price
    - int32 bid price
    - int32 ask volume
    - int32 bid volume
    """

    def __init__(
        self,
        *,
        path: str | Path,
        symbol: str,
        exchange: str,
        base_time: datetime | None = None,
        price_scale: int = 100_000,
        volume_scale: int = 100_000,
        byte_order: str = ">",
    ) -> None:
        super().__init__(symbol=symbol, exchange=exchange)
        self.path = Path(path)
        self.base_time = base_time or _infer_base_time(self.path)
        self.price_scale = price_scale
        self.volume_scale = volume_scale
        self.byte_order = byte_order

        if self.base_time is None:
            raise ValueError("Unable to infer base_time; provide base_time explicitly.")

    def iter_ticks(self) -> Iterable[TickRecord]:
        raw = _decompress_bi5(self.path)
        if not raw:
            return []

        record_size = 20
        unpack = struct.Struct(f"{self.byte_order}IIIII").unpack_from
        base = self.base_time

        for offset in range(0, len(raw) - record_size + 1, record_size):
            time_ms, ask, bid, ask_vol, bid_vol = unpack(raw, offset)
            ts = base + timedelta(milliseconds=time_ms)
            price = ((ask + bid) / 2.0) / self.price_scale
            volume = (ask_vol + bid_vol) / self.volume_scale
            yield TickRecord(time=ts, price=price, volume=volume)


def dukascopy_bi5_importer(
    path: str | Path,
    *,
    symbol: str,
    exchange: str,
    base_time: datetime | None = None,
    price_scale: int = 100_000,
    volume_scale: int = 100_000,
) -> DukascopyBi5Importer:
    return DukascopyBi5Importer(
        path=path,
        symbol=symbol,
        exchange=exchange,
        base_time=base_time,
        price_scale=price_scale,
        volume_scale=volume_scale,
    )


def _decompress_bi5(path: Path) -> bytes:
    raw = path.read_bytes()
    try:
        return lzma.decompress(raw)
    except lzma.LZMAError:
        filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 23}]
        return lzma.decompress(raw, format=lzma.FORMAT_RAW, filters=filters)


def _infer_base_time(path: Path) -> datetime | None:
    name = path.name
    match = re.search(r"(?P<date>\d{8})_(?P<hour>\d{2})h", name)
    if match:
        date_part = match.group("date")
        hour = match.group("hour")
        try:
            return datetime.strptime(f"{date_part}{hour}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Expected path segment: /YYYY/MM/DD/HHh_ticks.bi5
    parts = path.as_posix().split("/")
    for idx in range(len(parts) - 1):
        if parts[idx].isdigit() and len(parts[idx]) == 4:
            try:
                year = int(parts[idx])
                month = int(parts[idx + 1]) + 1
                day = int(parts[idx + 2])
                hour_part = parts[idx + 3]
                if hour_part.endswith("h_ticks.bi5"):
                    hour = int(hour_part.split("h")[0])
                else:
                    hour = int(hour_part[:2])
                return datetime(year, month, day, hour, tzinfo=timezone.utc)
            except Exception:
                continue
    return None
