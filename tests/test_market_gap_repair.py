from datetime import datetime, timedelta, timezone

from app.models.ticks import Asset, Tick


def test_market_gap_repair_dry_run(client, db_session):
    start = datetime(2025, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(seconds=2)

    asset = Asset(symbol="BTC-USD", exchange="coinbase", base="BTC", quote="USD", active=True)
    db_session.add(asset)
    db_session.flush()
    db_session.add_all(
        [
            Tick(
                asset_id=asset.id,
                time=start,
                price=100.0,
                volume=1.0,
                side="buy",
            ),
            Tick(
                asset_id=asset.id,
                time=start + timedelta(seconds=2),
                price=101.0,
                volume=1.0,
                side="sell",
            ),
        ]
    )
    db_session.commit()

    resp = client.post(
        "/api/market/gaps/repair/coinbase/BTC-USD",
        params={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bucket_seconds": 1,
            "import_source": "binance_vision",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["queued"] is False
    assert payload["planned_tasks"]
