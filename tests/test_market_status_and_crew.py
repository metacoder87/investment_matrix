from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.instrument import Coin, Price
from app.models.paper import PaperAccount, PaperOrder
from app.models.research import AgentGuardrailProfile, AgentRecommendation, AgentRun, AssetDataStatus
from app.services.crew_runner import AgentDecision
from app.signals.engine import Signal, SignalType
from celery_worker.tasks import backfill_historical_candles


class FakeRedisCache:
    async def get(self, key: str):
        return None

    async def setex(self, key: str, ttl: int, value: str):
        return True

    async def llen(self, key: str):
        return 0


class UnsupportedCoinbase:
    def __init__(self, config=None):
        self.config = config or {}

    async def load_markets(self):
        return {"BTC/USD": {}}

    def parse_timeframe(self, timeframe: str):
        return 60

    def milliseconds(self):
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    async def close(self):
        return None


def _seed_coin(db_session, symbol: str, name: str, rank: int):
    db_session.add(
        Coin(
            id=name.lower().replace(" ", "-"),
            symbol=symbol.lower(),
            name=name,
            market_cap_rank=rank,
            market_cap=1000,
            current_price=100,
            image=f"/{symbol.lower()}.png",
        )
    )


def _seed_prices(db_session, symbol: str = "BTC-USD", exchange: str = "coinbase", count: int = 60):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for idx in range(count):
        price = 100 + idx
        db_session.add(
            Price(
                exchange=exchange,
                symbol=symbol,
                timestamp=start + timedelta(minutes=idx),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=10,
            )
        )


def _seed_recent_prices(db_session, symbol: str = "BTC-USD", exchange: str = "coinbase", count: int = 240):
    start = datetime.now(timezone.utc) - timedelta(minutes=count)
    for idx in range(count):
        price = 200 - (idx * 0.1)
        db_session.add(
            Price(
                exchange=exchange,
                symbol=symbol,
                timestamp=start + timedelta(minutes=idx),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=10,
            )
        )
    latest = start + timedelta(minutes=count - 1)
    db_session.add(
        AssetDataStatus(
            exchange=exchange,
            symbol=symbol,
            base_symbol=symbol.split("-", 1)[0],
            status="ready",
            is_supported=True,
            is_analyzable=True,
            row_count=count,
            latest_candle_at=latest,
        )
    )


def test_coins_returns_explicit_signal_statuses(client, db_session):
    _seed_coin(db_session, "BTC", "Bitcoin", 1)
    _seed_coin(db_session, "USDC", "USDC", 2)
    _seed_prices(db_session)
    _seed_prices(db_session, symbol="USDC-USD")
    db_session.commit()

    btc_signal = Signal(
        symbol="BTC-USD",
        signal_type=SignalType.BUY,
        confidence=0.7,
        price=100,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reasons=["test"],
        indicators={"rsi": 50},
    )
    usdc_signal = Signal(
        symbol="USDC-USD",
        signal_type=SignalType.BUY,
        confidence=0.7,
        price=1,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reasons=["test"],
        indicators={"rsi": 50},
    )

    with patch("app.main.redis_client", FakeRedisCache()), patch(
        "app.main.SignalEngine.generate_signals_batch",
        return_value=[btc_signal, usdc_signal],
    ):
        response = client.get("/api/coins?source=db&limit=10")

    assert response.status_code == 200
    payload = response.json()
    btc = next(item for item in payload if item["symbol"] == "btc")
    usdc = next(item for item in payload if item["symbol"] == "usdc")
    assert btc["analysis"]["signal"] == "BUY"
    assert btc["analysis"]["status"] == "ready"
    assert btc["data_status"]["row_count"] == 60
    assert usdc["analysis"]["signal"] is None
    assert usdc["analysis"]["status"] == "not_applicable"


def test_coins_ready_data_overrides_old_backfill_failure(client, db_session):
    _seed_coin(db_session, "BTC", "Bitcoin", 1)
    _seed_prices(db_session, count=60)
    db_session.add(
        AssetDataStatus(
            exchange="coinbase",
            symbol="BTC-USD",
            base_symbol="BTC",
            status="backfill_failed",
            is_supported=True,
            is_analyzable=True,
            row_count=60,
            latest_candle_at=datetime(2026, 1, 1, 0, 59, tzinfo=timezone.utc),
            last_failure_reason="Rate limited during incremental backfill",
        )
    )
    db_session.commit()

    signal = Signal(
        symbol="BTC-USD",
        signal_type=SignalType.BUY,
        confidence=0.7,
        price=100,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reasons=["test"],
        indicators={"rsi": 50},
    )

    with patch("app.main.redis_client", FakeRedisCache()), patch(
        "app.main.SignalEngine.generate_signals_batch",
        return_value=[signal],
    ):
        response = client.get("/api/coins?source=db&limit=10")

    assert response.status_code == 200
    btc = response.json()[0]
    assert btc["analysis"]["signal"] == "BUY"
    assert btc["analysis"]["status"] == "ready"


def test_coins_analyzable_only_hides_not_applicable_assets(client, db_session):
    _seed_coin(db_session, "BTC", "Bitcoin", 1)
    _seed_coin(db_session, "USDC", "USDC", 2)
    _seed_prices(db_session)
    db_session.commit()

    with patch("app.main.redis_client", FakeRedisCache()), patch(
        "app.main.SignalEngine.generate_signals_batch",
        return_value=[],
    ):
        response = client.get("/api/coins?source=db&limit=10&analyzable_only=true")

    assert response.status_code == 200
    symbols = {item["symbol"] for item in response.json()}
    assert "btc" in symbols
    assert "usdc" not in symbols


def test_backfill_marks_unsupported_market_without_retrying(db_session):
    @contextmanager
    def scope():
        yield db_session
        db_session.commit()

    with patch("celery_worker.tasks.session_scope", scope), patch("celery_worker.tasks.ccxt.coinbase", UnsupportedCoinbase):
        result = backfill_historical_candles.run("LEO-USD", exchange_id="coinbase", days=1)

    assert result["status"] == "unsupported"
    status = (
        db_session.query(AssetDataStatus)
        .filter(AssetDataStatus.exchange == "coinbase", AssetDataStatus.symbol == "LEO-USD")
        .first()
    )
    assert status is not None
    assert status.status == "unsupported"
    assert "does not have market symbol" in status.last_failure_reason


def test_autonomous_recommendation_requires_backtest(client, db_session, test_user, auth_headers):
    account = PaperAccount(
        user_id=test_user.id,
        name="Agent Paper",
        cash_balance=10000,
        last_equity=10000,
        equity_peak=10000,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    response = client.post(
        "/api/crew/recommendations",
        headers=auth_headers,
        json={
            "agent_name": "Momentum Agent",
            "strategy_name": "sma_cross",
            "symbol": "BTC-USD",
            "exchange": "coinbase",
            "action": "buy",
            "confidence": 0.82,
            "thesis": "Test thesis",
            "paper_account_id": account.id,
            "auto_execute": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert "backtest is required" in payload["execution_reason"]

    audit_response = client.get("/api/crew/audit", headers=auth_headers)
    assert audit_response.status_code == 200
    assert any(event["event_type"] == "paper_trade_blocked" for event in audit_response.json())


def test_crew_runtime_disabled_is_clear(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.crew_runner.settings.CREW_ENABLED", False)
    response = client.get("/api/crew/runtime", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["status"] == "disabled"


def test_crew_run_disabled_returns_failed_setup_state(client, db_session, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.crew_runner.settings.CREW_ENABLED", False)

    response = client.post("/api/crew/runs", headers=auth_headers, json={"symbols": ["BTC-USD"], "max_symbols": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "disabled" in payload["error_message"].lower()
    assert db_session.query(AgentRun).count() == 1


def test_crew_run_rejects_malformed_agent_output(client, db_session, test_user, auth_headers, monkeypatch):
    _seed_recent_prices(db_session)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.crew_runner.runtime_status",
        lambda: {
            "enabled": True,
            "available": True,
            "provider": "ollama",
            "base_url": "http://ollama",
            "model": "test",
            "status": "available",
            "message": "ok",
        },
    )

    with patch("app.services.crew_runner.OllamaCrewClient.generate_decision", side_effect=ValueError("bad json")):
        response = client.post("/api/crew/runs", headers=auth_headers, json={"symbols": ["BTC-USD"], "max_symbols": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["recommendations"] == []
    assert any(event["event_type"] == "agent_output_rejected" for event in payload["audit"])


def test_crew_run_creates_prediction_backtest_and_guarded_paper_trade(client, db_session, test_user, auth_headers, monkeypatch):
    _seed_recent_prices(db_session, count=260)
    account = PaperAccount(
        user_id=test_user.id,
        name="Crew Paper",
        cash_balance=10000,
        last_equity=10000,
        equity_peak=10000,
    )
    guardrails = AgentGuardrailProfile(
        user_id=test_user.id,
        autonomous_enabled=True,
        max_position_pct=0.10,
        max_daily_loss_pct=0.50,
        max_open_positions=5,
        max_trades_per_day=10,
        min_data_freshness_seconds=86400,
        min_backtest_return_pct=-100.0,
        min_backtest_sharpe=-1_000_000.0,
        allowed_symbols=[],
    )
    db_session.add_all([account, guardrails])
    db_session.commit()
    db_session.refresh(account)

    monkeypatch.setattr(
        "app.services.crew_runner.runtime_status",
        lambda: {
            "enabled": True,
            "available": True,
            "provider": "ollama",
            "base_url": "http://ollama",
            "model": "test",
            "status": "available",
            "message": "ok",
        },
    )
    decision = AgentDecision(
        action="buy",
        confidence=0.82,
        thesis="Momentum is oversold enough for a supervised paper entry.",
        risk_notes="Paper trade only; validate drawdown.",
        strategy_name="rsi",
        strategy_params={"length": 2, "buy_threshold": 100.0, "sell_threshold": 101.0},
        prediction_summary="Small mean-reversion bounce expected.",
        prediction_horizon_minutes=240,
        predicted_path=[{"minutes_ahead": 240, "price": 190}],
    )

    with patch("app.services.crew_runner.OllamaCrewClient.generate_decision", return_value=decision):
        response = client.post(
            "/api/crew/runs",
            headers=auth_headers,
            json={"symbols": ["BTC-USD"], "max_symbols": 1, "paper_account_id": account.id, "auto_execute": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["snapshots"]
    assert payload["predictions"]
    assert payload["recommendations"]

    recommendation = db_session.query(AgentRecommendation).one()
    assert recommendation.prediction_id is not None
    assert recommendation.backtest_run_id is not None
    assert recommendation.status == "executed", recommendation.execution_reason
    assert db_session.query(PaperOrder).count() == 1
    assert any(event["event_type"] == "paper_trade_executed" for event in payload["audit"])
