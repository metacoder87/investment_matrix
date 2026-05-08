import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect

from app.models.research import DataSourceHealth
from app.services.ingestion_telemetry import collect_ingestion_telemetry, latest_capacity_snapshot


class FakeRedis:
    async def xlen(self, stream_key):
        return {"market_trades": 100, "market_quotes": 25}.get(stream_key, 0)

    async def xpending(self, stream_key, group):
        return {"pending": 10 if stream_key == "market_trades" else 5}


def test_collect_ingestion_telemetry_updates_source_health(db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion_telemetry.settings.STREAM_REDIS_MAX_PENDING", 100)
    monkeypatch.setattr("app.services.ingestion_telemetry.settings.STREAM_WRITER_MAX_LAG_SECONDS", 60)
    now = datetime.now(timezone.utc)
    db_session.add(
        DataSourceHealth(
            source="kraken",
            source_type="cex",
            enabled=True,
            last_event_at=now - timedelta(seconds=30),
        )
    )
    db_session.commit()

    result = asyncio.run(collect_ingestion_telemetry(db_session, redis=FakeRedis()))
    db_session.commit()

    assert result["status"] == "ok"
    assert result["redis"]["market_trades"]["length"] == 100
    row = db_session.query(DataSourceHealth).filter(DataSourceHealth.source == "kraken").one()
    assert row.redis_stream_length == 125
    assert row.redis_pending_messages == 15
    assert row.writer_lag_seconds >= 30
    assert row.db_pressure >= 0.5

    snapshot = latest_capacity_snapshot(db_session)
    assert snapshot["state"] == "normal"
    assert snapshot["redis_pending_messages"] == 15


def test_capacity_schema_columns_exist(db_session):
    inspector = inspect(db_session.bind)
    source_columns = {column["name"] for column in inspector.get_columns("data_source_health")}
    target_columns = {column["name"] for column in inspector.get_columns("stream_targets")}
    quote_columns = {column["name"] for column in inspector.get_columns("market_quotes")}

    assert {"redis_stream_length", "writer_lag_seconds", "db_pressure", "last_telemetry_at"} <= source_columns
    assert {"coverage_tier", "capacity_state", "expected_messages_per_second"} <= target_columns
    assert {"exchange", "symbol", "timestamp", "spread_bps"} <= quote_columns
