from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from app.config import settings


@dataclass(frozen=True)
class DownloadSpec:
    url: str
    destination: Path
    source_key: str


def _safe_symbol(symbol: str) -> str:
    return symbol.replace("-", "").replace("/", "").upper()


def _dukascopy_symbol(symbol: str) -> str:
    return "".join(ch for ch in symbol.upper() if ch.isalnum())


def binance_vision_daily_url(symbol: str, day: date, kind: str) -> str:
    pair = _safe_symbol(symbol)
    if kind not in {"trades", "aggTrades"}:
        raise ValueError(f"Unsupported Binance Vision kind: {kind}")
    return (
        f"https://data.binance.vision/data/spot/daily/{kind}/"
        f"{pair}/{pair}-{kind}-{day.isoformat()}.zip"
    )


def dukascopy_hourly_url(symbol: str, dt: datetime) -> str:
    pair = _dukascopy_symbol(symbol)
    year = dt.year
    month = f"{dt.month - 1:02d}"
    day = f"{dt.day:02d}"
    hour = f"{dt.hour:02d}"
    return f"https://datafeed.dukascopy.com/datafeed/{pair}/{year}/{month}/{day}/{hour}h_ticks.bi5"


def build_download_spec(url: str, filename: str) -> DownloadSpec:
    dest_dir = Path(settings.IMPORT_DATA_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = dest_dir / filename
    return DownloadSpec(url=url, destination=destination, source_key=url)


def download_file(spec: DownloadSpec, *, overwrite: bool = False) -> Path:
    if spec.destination.exists() and not overwrite:
        return spec.destination

    spec.destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(spec.url, stream=True, timeout=settings.IMPORT_HTTP_TIMEOUT_SECONDS)
    if response.status_code == 404:
        raise FileNotFoundError(f"Remote file not found: {spec.url}")
    response.raise_for_status()

    with open(spec.destination, "wb") as handle:
        for chunk in response.iter_content(chunk_size=settings.IMPORT_DOWNLOAD_CHUNK_BYTES):
            if not chunk:
                continue
            handle.write(chunk)

    return spec.destination


def date_range(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days
