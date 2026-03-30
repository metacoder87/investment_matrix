from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.imports import ImportRun
from app.services.imports.base import BaseTickImporter
from app.services.imports.storage import bulk_insert_ticks, get_or_create_asset
from app.services.imports.types import TickRecord


def record_import_start(
    db: Session,
    *,
    source: str,
    kind: str,
    symbol: str,
    exchange: str,
    owner_id: str | None,
    source_key: str,
    file_path: str | None,
) -> ImportRun:
    existing = (
        db.query(ImportRun)
        .filter(
            ImportRun.source == source,
            ImportRun.kind == kind,
            ImportRun.symbol == symbol,
            ImportRun.exchange == exchange,
            ImportRun.owner_id == owner_id,
            ImportRun.source_key == source_key,
        )
        .one_or_none()
    )
    now = datetime.now(timezone.utc)
    if existing and existing.status != "success":
        existing.status = "started"
        existing.started_at = now
        existing.finished_at = None
        existing.row_count = None
        existing.error = None
        existing.file_path = file_path
        return existing

    run = ImportRun(
        source=source,
        kind=kind,
        symbol=symbol,
        exchange=exchange,
        owner_id=owner_id,
        source_key=source_key,
        file_path=file_path,
        status="started",
        started_at=now,
    )
    db.add(run)
    db.flush()
    return run


def record_import_finish(
    db: Session,
    run: ImportRun,
    *,
    row_count: int,
    status: str,
    error: str | None = None,
) -> None:
    run.status = status
    run.row_count = row_count
    run.error = error
    run.finished_at = datetime.now(timezone.utc)


def already_imported(
    db: Session,
    *,
    source: str,
    kind: str,
    symbol: str,
    exchange: str,
    owner_id: str | None,
    source_key: str,
) -> bool:
    return (
        db.query(ImportRun)
        .filter(
            ImportRun.source == source,
            ImportRun.kind == kind,
            ImportRun.symbol == symbol,
            ImportRun.exchange == exchange,
            ImportRun.owner_id == owner_id,
            ImportRun.source_key == source_key,
            ImportRun.status == "success",
        )
        .first()
        is not None
    )


def ingest_ticks(
    db: Session,
    *,
    importer: BaseTickImporter,
    source: str,
    kind: str,
    source_key: str,
    owner_id: str | None = None,
    ingest_source: str | None = None,
    batch_size: int = 5000,
) -> int:
    if already_imported(
        db,
        source=source,
        kind=kind,
        symbol=importer.symbol,
        exchange=importer.exchange,
        owner_id=owner_id,
        source_key=source_key,
    ):
        return 0

    run = record_import_start(
        db,
        source=source,
        kind=kind,
        symbol=importer.symbol,
        exchange=importer.exchange,
        owner_id=owner_id,
        source_key=source_key,
        file_path=str(getattr(importer, "path", "") or ""),
    )

    asset = get_or_create_asset(
        db,
        symbol=importer.symbol,
        exchange=importer.exchange,
    )

    total = 0
    batch: list[TickRecord] = []
    try:
        for tick in importer.iter_ticks():
            batch.append(tick)
            if len(batch) >= batch_size:
                total += bulk_insert_ticks(
                    db,
                    asset_id=asset.id,
                    rows=batch,
                    ingest_source=ingest_source,
                    owner_id=owner_id,
                )
                batch.clear()

        if batch:
            total += bulk_insert_ticks(
                db,
                asset_id=asset.id,
                rows=batch,
                ingest_source=ingest_source,
                owner_id=owner_id,
            )

        record_import_finish(db, run, row_count=total, status="success")
        return total
    except Exception as exc:
        record_import_finish(db, run, row_count=total, status="failed", error=str(exc))
        raise
