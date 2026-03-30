from __future__ import annotations

import csv
import gzip
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.services.imports.base import BaseTickImporter
from app.services.imports.types import TickRecord


def _parse_timestamp(value: str, unit: str | None) -> datetime:
    raw = value.strip()
    if unit == "iso":
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    try:
        numeric = float(raw)
    except ValueError as exc:
        raise ValueError(f"Unsupported timestamp value: {value!r}") from exc

    if unit in {None, ""}:
        # Auto-detect based on magnitude.
        if numeric > 1e14:
            unit = "us"
        elif numeric > 1e12:
            unit = "ms"
        elif numeric > 1e9:
            unit = "s"
        else:
            unit = "s"

    divisor = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}.get(unit)
    if divisor is None:
        raise ValueError(f"Unsupported time_unit={unit!r}")

    return datetime.fromtimestamp(numeric / divisor, tz=timezone.utc)


def _open_text_stream(path: str | Path) -> io.TextIOBase:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    suffix = file_path.suffix.lower()
    if suffix == ".gz":
        return gzip.open(file_path, mode="rt", newline="")
    if suffix == ".zip":
        zf = zipfile.ZipFile(file_path)
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError(f"No CSV file found in {file_path.name}")
        if len(names) > 1:
            raise ValueError(
                f"Multiple CSV files found in {file_path.name}; "
                f"specify a single-file ZIP for now."
            )
        return io.TextIOWrapper(zf.open(names[0]), newline="")
    return open(file_path, mode="r", newline="")


class CsvTickImporter(BaseTickImporter):
    """
    Generic CSV importer with a column mapping.

    Required mapping keys: time, price, volume
    Optional keys: side, trade_id
    """

    def __init__(
        self,
        *,
        path: str | Path,
        symbol: str,
        exchange: str,
        mapping: dict[str, str],
        time_unit: str | None = None,
        side_map: dict[str, str] | None = None,
        is_aggregated: bool = False,
    ) -> None:
        super().__init__(symbol=symbol, exchange=exchange)
        self.path = Path(path)
        self.mapping = mapping
        self.time_unit = time_unit
        self.side_map = side_map or {}
        self.is_aggregated = is_aggregated

        missing = [k for k in ("time", "price", "volume") if k not in mapping]
        if missing:
            raise ValueError(f"Missing required mapping keys: {', '.join(missing)}")

    def iter_ticks(self) -> Iterable[TickRecord]:
        with _open_text_stream(self.path) as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts_raw = row.get(self.mapping["time"])
                price_raw = row.get(self.mapping["price"])
                volume_raw = row.get(self.mapping["volume"])
                if ts_raw is None or price_raw is None or volume_raw is None:
                    continue

                time = _parse_timestamp(ts_raw, self.time_unit)
                price = float(price_raw)
                volume = float(volume_raw)

                side = None
                if "side" in self.mapping:
                    side_raw = row.get(self.mapping["side"])
                    if side_raw:
                        side = self.side_map.get(side_raw, side_raw).lower()

                trade_id = None
                if "trade_id" in self.mapping:
                    trade_id = row.get(self.mapping["trade_id"]) or None

                yield TickRecord(
                    time=time,
                    price=price,
                    volume=volume,
                    side=side,
                    exchange_trade_id=trade_id,
                    is_aggregated=self.is_aggregated,
                )
