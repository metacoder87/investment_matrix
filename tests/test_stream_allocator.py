from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.instrument import Coin
from app.models.research import AssetDataStatus, DataSourceHealth, ExchangeMarket, MarketQuote, StreamTarget
from app.services.data_sources import list_data_sources
from app.services.stream_allocator import allocate_stream_targets, list_stream_targets, set_stream_preferences


def _market(exchange, symbol, base, quote="USD"):
    return ExchangeMarket(
        exchange=exchange,
        ccxt_symbol=symbol.replace("-", "/"),
        db_symbol=symbol,
        base=base,
        quote=quote,
        spot=True,
        active=True,
        is_analyzable=True,
    )


def test_allocator_respects_locked_blocked_and_exchange_cap(db_session, monkeypatch):
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "kraken")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE", 1)
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_LOCKED_SYMBOLS", "ETH-USD")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_BLOCKED_SYMBOLS", "DOGE-USD")
    now = datetime.now(timezone.utc)

    db_session.add(DataSourceHealth(source="kraken", source_type="cex", enabled=True, websocket_supported=True, rest_supported=True, last_success_at=now))
    db_session.add_all(
        [
            _market("kraken", "BTC-USD", "BTC"),
            _market("kraken", "ETH-USD", "ETH"),
            _market("kraken", "DOGE-USD", "DOGE"),
        ]
    )
    db_session.add_all(
        [
            Coin(id="bitcoin", symbol="btc", name="Bitcoin", market_cap=Decimal("1000000000000"), price_change_percentage_24h=1.0),
            Coin(id="ethereum", symbol="eth", name="Ethereum", market_cap=Decimal("500000000000"), price_change_percentage_24h=2.0),
            Coin(id="dogecoin", symbol="doge", name="Dogecoin", market_cap=Decimal("10000000000"), price_change_percentage_24h=10.0),
        ]
    )
    db_session.add(
        AssetDataStatus(
            exchange="kraken",
            symbol="ETH-USD",
            base_symbol="ETH",
            status="ready",
            row_count=500,
            latest_candle_at=now - timedelta(minutes=2),
            is_supported=True,
            is_analyzable=True,
        )
    )
    db_session.commit()

    result = allocate_stream_targets(db_session)
    db_session.commit()

    assert result["active"] == 1
    assert result["replacements"] == {"kraken": ["ETH-USD"]}
    eth = db_session.query(StreamTarget).filter(StreamTarget.symbol == "ETH-USD").one()
    doge = db_session.query(StreamTarget).filter(StreamTarget.symbol == "DOGE-USD").one()
    assert eth.active is True
    assert eth.user_preference == "locked"
    assert doge.status == "blocked"
    assert doge.active is False


def test_stream_preference_updates_existing_targets(db_session):
    db_session.add(_market("kraken", "BTC-USD", "BTC"))
    db_session.add(StreamTarget(exchange="kraken", symbol="BTC-USD", base="BTC", quote="USD", score=0.1))
    db_session.commit()

    result = set_stream_preferences(db_session, symbols=["BTC/USD"], preference="boosted")
    db_session.commit()

    assert result["updated"] == 1
    target = db_session.query(StreamTarget).filter(StreamTarget.symbol == "BTC-USD").one()
    assert target.user_preference == "boosted"


def test_list_data_sources_seeds_catalog(db_session):
    payload = list_data_sources(db_session)
    assert any(item["source"] == "kraken" for item in payload)
    assert any(item["source"] == "dexscreener" and item["source_type"] == "dex" for item in payload)


def test_list_stream_targets_payload_includes_score_details(db_session):
    db_session.add(
        StreamTarget(
            exchange="okx",
            symbol="BTC-USDT",
            base="BTC",
            quote="USDT",
            status="active",
            rank=1,
            score=0.9,
            active=True,
            score_details_json={"liquidity": 1.0},
        )
    )
    db_session.commit()

    payload = list_stream_targets(db_session, status="active")
    assert payload["count"] == 1
    assert payload["items"][0]["score_details"]["liquidity"] == 1.0


def test_allocator_uses_quote_spread_in_score_details(db_session, monkeypatch):
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "okx")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE", 5)
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_LOCKED_SYMBOLS", "")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_BLOCKED_SYMBOLS", "")
    now = datetime.now(timezone.utc)

    db_session.add(DataSourceHealth(source="okx", source_type="cex", enabled=True, websocket_supported=True, quote_supported=True, last_success_at=now))
    db_session.add(_market("okx", "BTC-USDT", "BTC", "USDT"))
    db_session.add(Coin(id="bitcoin", symbol="btc", name="Bitcoin", market_cap=Decimal("1000000000000"), price_change_percentage_24h=5.0))
    db_session.add(
        MarketQuote(
            exchange="okx",
            symbol="BTC-USDT",
            timestamp=now,
            bid=99.0,
            ask=101.0,
            mid=100.0,
            spread_bps=200.0,
        )
    )
    db_session.commit()

    allocate_stream_targets(db_session)
    db_session.commit()

    target = db_session.query(StreamTarget).filter(StreamTarget.exchange == "okx", StreamTarget.symbol == "BTC-USDT").one()
    assert target.score_details_json["spread_quality"] == 0.0


def test_allocator_demotes_marginal_symbols_when_capacity_is_constrained(db_session, monkeypatch):
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "okx")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE", 5)
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_LOCKED_SYMBOLS", "")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_BLOCKED_SYMBOLS", "")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_DB_PRESSURE_HIGH_WATERMARK", 0.8)
    now = datetime.now(timezone.utc)

    db_session.add(
        DataSourceHealth(
            source="okx",
            source_type="cex",
            enabled=True,
            websocket_supported=True,
            quote_supported=True,
            recent_trades_supported=True,
            db_pressure=0.9,
            redis_pending_messages=100000,
            last_telemetry_at=now,
            last_success_at=now,
        )
    )
    db_session.add_all(
        [
            _market("okx", "BTC-USDT", "BTC", "USDT"),
            _market("okx", "ETH-USDT", "ETH", "USDT"),
            _market("okx", "SOL-USDT", "SOL", "USDT"),
            _market("okx", "XRP-USDT", "XRP", "USDT"),
        ]
    )
    db_session.commit()

    result = allocate_stream_targets(db_session)
    db_session.commit()

    assert result["active"] == 2
    targets = db_session.query(StreamTarget).filter(StreamTarget.exchange == "okx").all()
    assert sum(1 for target in targets if target.coverage_tier == "tick_stream") == 2
    assert any(target.coverage_tier == "quote_stream" for target in targets)
    assert all(target.capacity_state == "constrained" for target in targets)


def test_allocator_downranks_region_blocked_sources(db_session, monkeypatch):
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "binance")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_MAX_SYMBOLS_PER_EXCHANGE", 5)
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_LOCKED_SYMBOLS", "")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_USER_BLOCKED_SYMBOLS", "")
    now = datetime.now(timezone.utc)

    db_session.add(
        DataSourceHealth(
            source="binance",
            source_type="cex",
            enabled=True,
            websocket_supported=True,
            rest_supported=True,
            recent_trades_supported=True,
            ohlcv_supported=True,
            last_error_at=now,
            last_error="451 Service unavailable from a restricted location according to Eligibility.",
        )
    )
    db_session.add(_market("binance", "BTC-USDT", "BTC", "USDT"))
    db_session.commit()

    result = allocate_stream_targets(db_session)
    db_session.commit()

    assert result["active"] == 0
    assert result["replacements"] == {"binance": []}
    target = db_session.query(StreamTarget).filter(StreamTarget.exchange == "binance", StreamTarget.symbol == "BTC-USDT").one()
    assert target.active is False
    assert target.coverage_tier == "ohlcv_only"
    assert "region-blocked" in target.reason
    assert target.score_details_json["source_reliability"] == 0.0
    assert target.score_details_json["availability_reason"]
