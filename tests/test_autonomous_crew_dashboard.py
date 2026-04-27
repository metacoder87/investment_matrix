from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from app.models.instrument import Price
from app.models.paper import PaperAccount, PaperOrder, PaperPosition
from app.models.research import (
    AgentBankrollReset,
    AgentGuardrailProfile,
    AgentLesson,
    AgentModelInvocation,
    AgentRecommendation,
    AgentRun,
    AgentResearchThesis,
    AgentTraceEvent,
    AssetDataStatus,
)
from app.services.crew_autonomy import TradeApprovalDecision, ThesisDecision, monitor_price_triggers, run_autonomous_research_cycle
from app.services.crew_portfolio import maybe_reset_bankroll


def _seed_recent_prices(db_session, symbol: str = "BTC-USD", exchange: str = "coinbase", count: int = 260, base: float = 100.0):
    start = datetime.now(timezone.utc) - timedelta(minutes=count)
    for idx in range(count):
        price = base + idx * 0.05
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
    return base + (count - 1) * 0.05, latest


def _profile(user_id: int, **overrides):
    defaults = {
        "user_id": user_id,
        "autonomous_enabled": True,
        "research_enabled": True,
        "trigger_monitor_enabled": True,
        "research_interval_seconds": 1800,
        "max_position_pct": 0.35,
        "max_daily_loss_pct": 0.10,
        "max_open_positions": 12,
        "max_trades_per_day": 40,
        "min_data_freshness_seconds": 86400,
        "min_backtest_return_pct": -100.0,
        "min_backtest_sharpe": -1_000_000.0,
        "bankroll_reset_drawdown_pct": 0.95,
        "default_starting_bankroll": 10_000.0,
        "allowed_symbols": [],
    }
    defaults.update(overrides)
    return AgentGuardrailProfile(**defaults)


def test_crew_portfolio_summary_creates_default_ai_bankroll(client, auth_headers):
    response = client.get("/api/crew/portfolio/summary", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_name"] == "AI Team Bankroll"
    assert payload["available_bankroll"] == 10000
    assert payload["settings"]["max_position_pct"] == 0.35
    assert payload["settings"]["research_enabled"] is False
    assert payload["settings"]["trigger_monitor_enabled"] is False


def test_autonomous_research_creates_active_thesis_without_trade(db_session, test_user, monkeypatch):
    latest_price, _ = _seed_recent_prices(db_session)
    db_session.add(_profile(test_user.id))
    db_session.commit()
    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_RESEARCH_ENABLED", True)
    monkeypatch.setattr(
        "app.services.crew_autonomy.runtime_status",
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
    decision = ThesisDecision(
        action="buy",
        confidence=0.84,
        thesis="Momentum setup with nearby entry and defined exit targets.",
        risk_notes="Paper-only aggressive sizing.",
        strategy_name="buy_hold",
        strategy_params={},
        entry_condition="at_or_below",
        entry_target=latest_price + 1,
        take_profit_target=latest_price + 5,
        stop_loss_target=latest_price - 5,
        predicted_path=[{"minutes_ahead": 240, "price": latest_price + 5}],
    )

    with patch("app.services.crew_autonomy.OllamaThesisClient.generate_thesis", return_value=decision):
        result = run_autonomous_research_cycle(db_session, test_user, max_symbols=1)

    assert result["status"] == "completed"
    thesis = db_session.query(AgentResearchThesis).one()
    assert thesis.status == "active"
    assert thesis.entry_target == round(latest_price * 1.005, 10)
    assert thesis.take_profit_target == round(thesis.entry_target * 1.02, 10)
    assert thesis.stop_loss_target == round(thesis.entry_target * 0.985, 10)
    assert db_session.query(PaperOrder).count() == 0
    assert db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "thesis_created").count() == 1


def test_autonomous_research_prefers_kraken_ready_asset(db_session, test_user, monkeypatch):
    kraken_price, _ = _seed_recent_prices(db_session, exchange="kraken", count=260, base=200.0)
    _seed_recent_prices(db_session, exchange="coinbase", count=320, base=100.0)
    db_session.add(_profile(test_user.id))
    db_session.commit()
    monkeypatch.setattr("app.services.crew_runner.settings.PRICE_EXCHANGE_PRIORITY", "kraken,coinbase,binance")
    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_RESEARCH_ENABLED", True)
    monkeypatch.setattr(
        "app.services.crew_autonomy.runtime_status",
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
    decision = ThesisDecision(
        action="buy",
        confidence=0.81,
        thesis="Kraken-ready setup with enough candles and defined paper targets.",
        risk_notes="Paper-only aggressive sizing.",
        strategy_name="buy_hold",
        strategy_params={},
        entry_condition="at_or_below",
        entry_target=kraken_price + 1,
        take_profit_target=kraken_price + 5,
        stop_loss_target=kraken_price - 5,
    )

    with patch("app.services.crew_autonomy.OllamaThesisClient.generate_thesis", return_value=decision):
        result = run_autonomous_research_cycle(db_session, test_user, max_symbols=1)

    assert result["status"] == "completed"
    thesis = db_session.query(AgentResearchThesis).one()
    assert thesis.exchange == "kraken"
    assert thesis.symbol == "BTC-USD"


def test_trigger_monitor_buys_and_sells_on_targets(db_session, test_user, monkeypatch):
    latest_price, latest_ts = _seed_recent_prices(db_session, exchange="kraken")
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=10000,
        last_equity=10000,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id)
    db_session.add_all([account, profile])
    db_session.commit()
    db_session.refresh(account)
    profile.ai_paper_account_id = account.id
    thesis = AgentResearchThesis(
        user_id=test_user.id,
        account_id=account.id,
        exchange="kraken",
        symbol="BTC-USD",
        strategy_name="buy_hold",
        strategy_params={},
        side="buy",
        confidence=0.8,
        thesis="Buy target is close with defined exit.",
        entry_condition="at_or_below",
        entry_target=latest_price + 1,
        take_profit_target=latest_price + 3,
        stop_loss_target=latest_price - 3,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    db_session.add(thesis)
    db_session.flush()

    from app.models.backtest import BacktestRun
    recommendation = AgentRecommendation(
        user_id=test_user.id,
        agent_name="Portfolio Manager",
        strategy_name="buy_hold",
        exchange="kraken",
        symbol="BTC-USD",
        action="buy",
        confidence=0.8,
        thesis="Buy target is close with defined exit.",
        paper_account_id=account.id,
        status="proposed",
    )
    backtest = BacktestRun(
        user_id=test_user.id,
        name="test",
        symbol="BTC-USD",
        exchange="kraken",
        timeframe="1m",
        start=latest_ts - timedelta(days=1),
        end=latest_ts,
        initial_cash=10000,
        fee_rate=0.001,
        slippage_bps=5.0,
        max_position_pct=0.35,
        strategy="buy_hold",
        strategy_params={},
        metrics={"total_return_pct": 1, "sharpe_ratio": 1},
        equity_curve=[],
    )
    db_session.add_all([recommendation, backtest])
    db_session.flush()
    recommendation.backtest_run_id = backtest.id
    thesis.recommendation_id = recommendation.id
    db_session.commit()
    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    approval = TradeApprovalDecision(
        decision="approve",
        confidence=0.9,
        rationale="Triggered paper trade is consistent with the active thesis and guardrails.",
    )

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade", return_value=(approval, None)):
        buy_result = monitor_price_triggers(db_session, test_user)
    assert buy_result["executed"] == 1
    assert db_session.query(PaperPosition).count() == 1
    assert db_session.query(PaperOrder).count() == 1

    new_ts = latest_ts + timedelta(minutes=1)
    sell_price = latest_price + 4
    db_session.add(
        Price(
            exchange="kraken",
            symbol="BTC-USD",
            timestamp=new_ts,
            open=sell_price,
            high=sell_price,
            low=sell_price,
            close=sell_price,
            volume=20,
        )
    )
    status = db_session.query(AssetDataStatus).filter(AssetDataStatus.symbol == "BTC-USD").one()
    status.latest_candle_at = new_ts
    db_session.commit()

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade", return_value=(approval, None)):
        sell_result = monitor_price_triggers(db_session, test_user)
    assert sell_result["executed"] == 1
    assert db_session.query(PaperPosition).count() == 0
    assert db_session.query(PaperOrder).count() == 2
    assert {order.exchange for order in db_session.query(PaperOrder).all()} == {"kraken"}
    assert db_session.query(AgentLesson).filter(AgentLesson.outcome == "take_profit").count() == 1
    assert db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "paper_order_executed").count() == 2


def test_drawdown_reset_restores_bankroll_and_records_lesson(db_session, test_user):
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=400,
        last_equity=400,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id, ai_paper_account_id=None)
    db_session.add_all([account, profile])
    db_session.commit()
    db_session.refresh(account)
    profile.ai_paper_account_id = account.id

    reset = maybe_reset_bankroll(db_session, test_user)
    db_session.commit()

    assert reset is not None
    assert reset.reset_number == 1
    assert account.cash_balance == 10000
    assert account.last_equity == 10000
    assert db_session.query(AgentBankrollReset).count() == 1
    assert db_session.query(AgentLesson).filter(AgentLesson.outcome == "bankroll_reset").count() == 1


def test_start_bot_enables_current_user_and_queues_immediate_research(
    client,
    auth_headers,
    db_session,
    test_user,
    monkeypatch,
):
    _seed_recent_prices(db_session, exchange="kraken")
    db_session.commit()
    monkeypatch.setattr("app.routers.crew.settings.PRIMARY_EXCHANGE", "kraken")
    monkeypatch.setattr("app.routers.crew.settings.CREW_RESEARCH_ENABLED", True)
    monkeypatch.setattr("app.routers.crew.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    monkeypatch.setattr(
        "app.routers.crew.runtime_status",
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

    captured = {}

    class FakeTask:
        id = "research-task-1"

    def fake_send_task(name, args=None, kwargs=None):
        captured["name"] = name
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeTask()

    monkeypatch.setattr("app.routers.crew.celery_app.send_task", fake_send_task)

    response = client.post("/api/crew/autonomy/start", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert payload["primary_exchange"] == "kraken"
    assert payload["research_task_id"] == "research-task-1"
    assert captured["name"] == "celery_worker.tasks.run_crew_research_cycle_for_user"
    assert captured["args"] == [test_user.id]

    profile = db_session.query(AgentGuardrailProfile).filter(AgentGuardrailProfile.user_id == test_user.id).one()
    assert profile.autonomous_enabled is True
    assert profile.research_enabled is True
    assert profile.trigger_monitor_enabled is True
    assert profile.trade_cadence_mode == "aggressive_paper"
    assert profile.ai_paper_account_id is not None
    assert db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "autonomous_bot_started").count() == 1


def test_start_bot_requires_ready_primary_exchange_assets(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.routers.crew.settings.PRIMARY_EXCHANGE", "kraken")
    monkeypatch.setattr("app.routers.crew.settings.CREW_RESEARCH_ENABLED", True)
    monkeypatch.setattr("app.routers.crew.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    monkeypatch.setattr(
        "app.routers.crew.runtime_status",
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

    response = client.post("/api/crew/autonomy/start", headers=auth_headers)

    assert response.status_code == 409
    assert response.json()["detail"]["bot_state"] == "setup_needed"
    assert response.json()["detail"]["backfill_path"] == "/api/backfill/universe?exchange=kraken"


def test_pause_bot_disables_current_user_flags(client, auth_headers, db_session, test_user):
    db_session.add(_profile(test_user.id))
    db_session.commit()

    response = client.post("/api/crew/autonomy/pause", headers=auth_headers)

    assert response.status_code == 200
    profile = db_session.query(AgentGuardrailProfile).filter(AgentGuardrailProfile.user_id == test_user.id).one()
    assert profile.autonomous_enabled is False
    assert profile.research_enabled is False
    assert profile.trigger_monitor_enabled is False


def test_crew_activity_omits_debug_fields_by_default(client, auth_headers, db_session, test_user):
    db_session.add(
        AgentTraceEvent(
            user_id=test_user.id,
            role="Portfolio Manager",
            event_type="thesis_created",
            status="waiting",
            public_summary="BTC-USD thesis created.",
            rationale="Signal and backtest evidence aligned.",
            prompt="private prompt text",
            raw_model_json={"action": "buy"},
        )
    )
    db_session.commit()

    default_response = client.get("/api/crew/activity", headers=auth_headers)
    debug_response = client.get("/api/crew/activity?debug=true", headers=auth_headers)

    assert default_response.status_code == 200
    assert "prompt" not in default_response.json()[0]
    assert "raw_model_json" not in default_response.json()[0]
    assert default_response.json()[0]["created_at"].endswith("Z")
    assert debug_response.status_code == 200
    assert debug_response.json()[0]["prompt"] == "private prompt text"
    assert debug_response.json()[0]["raw_model_json"] == {"action": "buy"}


def test_model_routing_persists_and_model_probe_records_invocation(client, auth_headers, db_session, test_user, monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    monkeypatch.setattr("app.services.crew_models.settings.CREW_ENABLED", True)
    monkeypatch.setattr(
        "app.services.crew_models.requests.get",
        lambda *args, **kwargs: FakeResponse(
            {
                "models": [
                    {
                        "name": "fast-thesis:latest",
                        "model": "fast-thesis:latest",
                        "size": 123,
                        "details": {"family": "llama", "parameter_size": "8B", "quantization_level": "Q4"},
                    },
                    {
                        "name": "trade-checker:latest",
                        "model": "trade-checker:latest",
                        "size": 456,
                        "details": {"family": "qwen", "parameter_size": "14B", "quantization_level": "Q4"},
                    },
                ]
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.crew_models.requests.post",
        lambda *args, **kwargs: FakeResponse({"response": '{"status":"ok","model_test":true,"reason":"ready"}'}),
    )

    response = client.patch(
        "/api/crew/model-routing",
        headers=auth_headers,
        json={"default": "fast-thesis:latest", "trade": "trade-checker:latest"},
    )

    assert response.status_code == 200
    profile = db_session.query(AgentGuardrailProfile).filter(AgentGuardrailProfile.user_id == test_user.id).one()
    assert profile.default_llm_model == "fast-thesis:latest"
    assert profile.trade_llm_model == "trade-checker:latest"

    test_response = client.post(
        "/api/crew/model/test",
        headers=auth_headers,
        json={"role": "trade", "model": "trade-checker:latest"},
    )

    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True
    invocation = db_session.query(AgentModelInvocation).one()
    assert invocation.llm_model == "trade-checker:latest"
    assert invocation.action_type == "model_test"
    assert invocation.status == "success"

    performance_response = client.get("/api/crew/model-performance", headers=auth_headers)
    assert performance_response.status_code == 200
    row = performance_response.json()[0]
    assert row["latest_status"] == "success"
    assert row["timeout_rate_pct"] == 0


def test_no_trade_diagnostics_prioritizes_model_timeout(client, auth_headers, db_session, test_user, monkeypatch):
    monkeypatch.setattr(
        "app.routers.crew.runtime_payload",
        lambda profile, role="thesis": {
            "enabled": True,
            "available": True,
            "provider": "ollama",
            "base_url": "http://ollama",
            "model": "llama3.3:70b",
            "status": "available",
            "message": "ok",
        },
    )
    db_session.add(_profile(test_user.id, research_enabled=True, trigger_monitor_enabled=True))
    run = AgentRun(
        user_id=test_user.id,
        status="completed",
        mode="autonomous_research",
        llm_provider="ollama",
        llm_model="llama3.3:70b",
        summary={"theses_created": 0, "rejected": 3, "stopped_reason": "Thesis model llama3.3:70b timed out 3 times in a row."},
    )
    invocation = AgentModelInvocation(
        user_id=test_user.id,
        role="Thesis Strategist",
        action_type="research_thesis",
        llm_provider="ollama",
        llm_model="llama3.3:70b",
        status="timeout",
        timeout_seconds=60,
        error_message="Read timed out.",
    )
    db_session.add_all([run, invocation])
    db_session.commit()

    response = client.get("/api/crew/no-trade-diagnostics", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_thesis_count"] == 0
    assert payload["latest_model_failure"]["status"] == "timeout"
    assert any("llama3.3:70b" in blocker and "timed out" in blocker for blocker in payload["blockers"])
    assert "faster local thesis/trade model" in payload["recommended_action"]


def test_research_dry_run_endpoint_returns_service_result(client, auth_headers):
    expected = {"ok": True, "status": "ok", "model": "fast:latest", "symbol": "BTC-USD"}
    with patch("app.routers.crew.dry_run_research_thesis", return_value=expected) as mocked:
        response = client.post("/api/crew/research/dry-run", headers=auth_headers, json={"symbol": "BTC-USD"})

    assert response.status_code == 200
    assert response.json() == expected
    assert mocked.call_args.kwargs["symbol"] == "BTC-USD"


def test_autonomous_research_stops_after_repeated_thesis_model_timeouts(db_session, test_user, monkeypatch):
    for idx, symbol in enumerate(["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]):
        _seed_recent_prices(db_session, symbol=symbol, exchange="kraken", count=260, base=100.0 + idx)
    db_session.add(_profile(test_user.id, thesis_llm_model="llama3.3:70b"))
    db_session.commit()
    monkeypatch.setattr("app.services.crew_runner.settings.PRICE_EXCHANGE_PRIORITY", "kraken,coinbase,binance")
    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_RESEARCH_ENABLED", True)
    monkeypatch.setattr(
        "app.services.crew_autonomy.runtime_status",
        lambda: {
            "enabled": True,
            "available": True,
            "provider": "ollama",
            "base_url": "http://ollama",
            "model": "llama3.3:70b",
            "status": "available",
            "message": "ok",
        },
    )

    with patch(
        "app.services.crew_autonomy.OllamaThesisClient.generate_thesis",
        side_effect=requests.Timeout("Read timed out."),
    ):
        result = run_autonomous_research_cycle(db_session, test_user, max_symbols=4)

    assert result["stopped_reason"] is not None
    assert "timed out 3 times" in result["stopped_reason"]
    run = db_session.query(AgentRun).filter(AgentRun.mode == "autonomous_research").one()
    assert run.summary["stopped_reason"] == result["stopped_reason"]
    assert len(run.selected_symbols) == 3
    assert (
        db_session.query(AgentTraceEvent)
        .filter(AgentTraceEvent.event_type == "research_blocked_model_timeout")
        .count()
        == 1
    )


def test_trigger_monitor_blocks_when_trade_model_rejects(db_session, test_user, monkeypatch):
    latest_price, latest_ts = _seed_recent_prices(db_session, exchange="kraken")
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=10000,
        last_equity=10000,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id, trade_llm_model="trade-checker:latest")
    db_session.add_all([account, profile])
    db_session.commit()
    db_session.refresh(account)
    profile.ai_paper_account_id = account.id
    from app.models.backtest import BacktestRun

    thesis = AgentResearchThesis(
        user_id=test_user.id,
        account_id=account.id,
        exchange="kraken",
        symbol="BTC-USD",
        strategy_name="buy_hold",
        strategy_params={},
        side="buy",
        confidence=0.8,
        thesis="Buy target is close with defined exit.",
        entry_condition="at_or_below",
        entry_target=latest_price + 1,
        take_profit_target=latest_price + 3,
        stop_loss_target=latest_price - 3,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    recommendation = AgentRecommendation(
        user_id=test_user.id,
        agent_name="Portfolio Manager",
        strategy_name="buy_hold",
        exchange="kraken",
        symbol="BTC-USD",
        action="buy",
        confidence=0.8,
        thesis="Buy target is close with defined exit.",
        paper_account_id=account.id,
        status="proposed",
    )
    backtest = BacktestRun(
        user_id=test_user.id,
        name="test",
        symbol="BTC-USD",
        exchange="kraken",
        timeframe="1m",
        start=latest_ts - timedelta(days=1),
        end=latest_ts,
        initial_cash=10000,
        fee_rate=0.001,
        slippage_bps=5.0,
        max_position_pct=0.35,
        strategy="buy_hold",
        strategy_params={},
        metrics={"total_return_pct": 1, "sharpe_ratio": 1},
        equity_curve=[],
    )
    db_session.add_all([thesis, recommendation, backtest])
    db_session.flush()
    recommendation.backtest_run_id = backtest.id
    thesis.recommendation_id = recommendation.id
    db_session.commit()
    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    rejection = TradeApprovalDecision(
        decision="reject",
        confidence=0.7,
        rationale="Reject because the trigger context is not compelling enough.",
    )

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade", return_value=(rejection, None)):
        result = monitor_price_triggers(db_session, test_user)

    assert result["blocked"] == 1
    assert db_session.query(PaperOrder).count() == 0
    trigger_recommendation = (
        db_session.query(AgentRecommendation)
        .filter(AgentRecommendation.agent_name == "Trigger Monitor")
        .one()
    )
    assert trigger_recommendation.trade_decision_model == "trade-checker:latest"
    assert trigger_recommendation.trade_decision_status == "reject"
