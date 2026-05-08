from datetime import datetime, timezone

from app.models.research import AssetDataStatus, DataSourceHealth, ExchangeMarket, StreamTarget
from app.services.market_activation import activate_market_coverage, tiered_coverage_summary


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


def test_activate_market_coverage_creates_statuses_and_targets(db_session, monkeypatch):
    monkeypatch.setattr("app.services.market_activation.settings.STREAM_SOURCE_PRIORITY", "kraken,binance")
    monkeypatch.setattr("app.services.stream_allocator.settings.STREAM_SOURCE_PRIORITY", "kraken,binance")
    now = datetime.now(timezone.utc)
    db_session.add(
        DataSourceHealth(
            source="kraken",
            source_type="cex",
            enabled=True,
            websocket_supported=True,
            rest_supported=True,
            recent_trades_supported=True,
            ohlcv_supported=True,
            last_success_at=now,
        )
    )
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
    db_session.add_all(
        [
            _market("kraken", "ETH-USD", "ETH"),
            _market("binance", "BTC-USDT", "BTC", "USDT"),
        ]
    )
    db_session.commit()

    result = activate_market_coverage(db_session, queue_work=False)
    db_session.commit()

    assert result["evaluated"] == 2
    assert result["created_status"] == 2
    assert result["created_targets"] == 2
    assert result["unavailable"] == 1

    kraken_status = db_session.query(AssetDataStatus).filter_by(exchange="kraken", symbol="ETH-USD").one()
    binance_status = db_session.query(AssetDataStatus).filter_by(exchange="binance", symbol="BTC-USDT").one()
    assert kraken_status.status == "warming_up"
    assert binance_status.status == "unsupported"
    assert "region-blocked" in binance_status.last_failure_reason

    binance_target = db_session.query(StreamTarget).filter_by(exchange="binance", symbol="BTC-USDT").one()
    assert binance_target.coverage_tier == "ohlcv_only"
    assert "region-blocked" in binance_target.reason

    coverage = tiered_coverage_summary(db_session)
    assert coverage["total_targets"] == 2
    assert coverage["by_tier"]["tick_stream"] == 1
    assert coverage["by_tier"]["ohlcv_only"] == 1
