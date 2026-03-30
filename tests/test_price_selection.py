from datetime import datetime, timedelta, timezone

from app.models.instrument import Price
from app.config import settings
from app.services.price_selection import resolve_price_exchange


def test_resolve_price_exchange_prefers_latest(db_session):
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    db_session.add(
        Price(
            symbol="BTC-USD",
            exchange="coinbase",
            timestamp=now - timedelta(minutes=5),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
    )
    db_session.add(
        Price(
            symbol="BTC-USD",
            exchange="binance",
            timestamp=now,
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
    )
    db_session.commit()

    assert resolve_price_exchange(db_session, "BTC-USD") == "binance"


def test_resolve_price_exchange_override(db_session):
    assert resolve_price_exchange(db_session, "BTC-USD", exchange="kraken") == "kraken"


def test_resolve_price_exchange_falls_back_to_priority(db_session, monkeypatch):
    monkeypatch.setattr(settings, "PRICE_EXCHANGE_PRIORITY", "coinbase,binance")
    monkeypatch.setattr(settings, "STREAM_EXCHANGES", "")
    monkeypatch.setattr(settings, "STREAM_EXCHANGE", "")

    assert resolve_price_exchange(db_session, "NEW-TOKEN") == "coinbase"
