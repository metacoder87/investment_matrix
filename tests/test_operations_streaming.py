from app.models.research import ExchangeMarket, StreamTarget


def test_operations_data_sources_endpoint(client):
    response = client.get("/api/operations/data-sources")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 3
    assert any(item["source"] == "kraken" for item in payload["items"])


def test_operations_stream_target_preferences_endpoint(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "kraken")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE", 5)
    db_session.add(
        ExchangeMarket(
            exchange="kraken",
            ccxt_symbol="BTC/USD",
            db_symbol="BTC-USD",
            base="BTC",
            quote="USD",
            spot=True,
            active=True,
            is_analyzable=True,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/operations/stream-targets/preferences",
        json={"symbols": ["BTC-USD"], "preference": "locked", "exchange": "kraken"},
    )
    assert response.status_code == 200
    assert response.json()["preference"] == "locked"
    target = db_session.query(StreamTarget).filter(StreamTarget.exchange == "kraken", StreamTarget.symbol == "BTC-USD").one()
    assert target.user_preference == "locked"

    list_response = client.get("/api/operations/stream-targets", params={"status": "active"})
    assert list_response.status_code == 200
    assert list_response.json()["items"]


def test_operations_market_reports_tiered_coverage(client, db_session):
    db_session.add(
        StreamTarget(
            exchange="kraken",
            symbol="BTC-USD",
            base="BTC",
            quote="USD",
            status="active",
            coverage_tier="tick_stream",
            capacity_state="normal",
            active=True,
            score=1.0,
        )
    )
    db_session.commit()

    response = client.get("/api/operations/market")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tiered_coverage"]["by_tier"]["tick_stream"] == 1


def test_operations_activate_coverage_endpoint(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.market_activation.settings.STREAM_SOURCE_PRIORITY", "kraken")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "kraken")
    db_session.add(
        ExchangeMarket(
            exchange="kraken",
            ccxt_symbol="ETH/USD",
            db_symbol="ETH-USD",
            base="ETH",
            quote="USD",
            spot=True,
            active=True,
            is_analyzable=True,
        )
    )
    db_session.commit()

    response = client.post("/api/operations/market/activate-coverage", params={"queue_work": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluated"] == 1
    assert payload["coverage"]["total_targets"] == 1
