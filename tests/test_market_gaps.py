from datetime import datetime, timedelta, timezone

from app.models.ticks import Asset, Tick


def test_market_gaps_detects_empty_buckets(client, db_session):
    start = datetime(2025, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
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

    resp = client.get(
        "/api/market/gaps/coinbase/BTC-USD",
        params={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bucket_seconds": 1,
            "max_points": 100,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["source"] == "ticks"
    assert payload["bucket_seconds"] == 1
    assert payload["total_buckets"] == 3
    assert payload["missing_buckets"] == 1
    assert len(payload["gaps"]) == 1
    gap = payload["gaps"][0]
    assert gap["start"] == (start + timedelta(seconds=1)).isoformat()
    assert gap["end"] == (start + timedelta(seconds=2)).isoformat()
