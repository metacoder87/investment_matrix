from datetime import datetime, timedelta, timezone

from app.models.ticks import Asset, Tick


def test_ingestion_health_reports_db_timestamp(client, db_session):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    asset = Asset(symbol="BTC-USD", exchange="coinbase", base="BTC", quote="USD", active=True)
    db_session.add(asset)
    db_session.flush()
    db_session.add(
        Tick(
            asset_id=asset.id,
            time=now - timedelta(seconds=5),
            price=100.0,
            volume=1.0,
            side="buy",
        )
    )
    db_session.commit()

    resp = client.get("/api/system/ingestion/health?exchange=coinbase&symbols=BTC-USD&lookback_hours=1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["exchange"] == "coinbase"
    assert payload["symbols"]
    entry = payload["symbols"][0]
    assert entry["symbol"] == "BTC-USD"
    assert entry["latest_db_timestamp"] is not None
