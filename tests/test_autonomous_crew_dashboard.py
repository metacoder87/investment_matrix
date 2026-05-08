from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.instrument import Price
from app.models.paper import PaperAccount, PaperOrder, PaperPosition
from app.models.research import (
    AgentBankrollReset,
    AgentFormulaSuggestion,
    AgentGuardrailProfile,
    AgentLesson,
    AgentModelInvocation,
    AgentRecommendation,
    AgentRun,
    AgentResearchThesis,
    AgentTraceEvent,
    AssetDataStatus,
)
from app.services.crew_autonomy import monitor_price_triggers, run_autonomous_research_cycle
from app.services.crew_formula_decisions import (
    AUTHORITY_AUTO_APPLY_BOUNDED,
    FORMULA_ENGINE_MODEL,
    get_or_create_formula_config,
    maybe_create_formula_suggestion,
    update_formula_config,
)
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


def test_crew_portfolio_and_diagnostics_report_position_exit_health(client, auth_headers, db_session, test_user):
    latest_price, _ = _seed_recent_prices(db_session, exchange="kraken")
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=9000,
        last_equity=10000,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id)
    db_session.add_all([account, profile])
    db_session.commit()
    db_session.refresh(account)
    profile.ai_paper_account_id = account.id
    position = PaperPosition(
        account_id=account.id,
        exchange="kraken",
        symbol="BTC-USD",
        side="long",
        quantity=10,
        avg_entry_price=latest_price,
        last_price=latest_price,
        take_profit=latest_price + 5,
        stop_loss=latest_price - 5,
    )
    db_session.add(position)
    db_session.commit()

    summary_response = client.get("/api/crew/portfolio/summary", headers=auth_headers)
    assert summary_response.status_code == 200
    position_payload = summary_response.json()["positions"][0]
    assert position_payload["exit_health"] == "managed"
    assert position_payload["exit_source"] == "position"
    assert position_payload["distance_to_take_profit_pct"] is not None
    assert position_payload["distance_to_stop_loss_pct"] is not None

    position.take_profit = None
    position.stop_loss = None
    db_session.commit()
    diagnostics_response = client.get("/api/crew/no-trade-diagnostics", headers=auth_headers)
    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    assert diagnostics["open_position_count"] == 1
    assert diagnostics["unmanaged_position_count"] == 1


def test_autonomous_research_creates_immediate_formula_paper_trade(db_session, test_user, monkeypatch):
    latest_price, _ = _seed_recent_prices(db_session)
    db_session.add(_profile(test_user.id))
    update_formula_config(
        db_session,
        test_user,
        parameters={"entry_score_floor": 0.1, "long": {"entry_threshold": 0.1}, "short": {"entry_threshold": 0.1}},
    )
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

    with patch("app.services.crew_autonomy.OllamaThesisClient.generate_thesis") as thesis_mock, patch(
        "app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade"
    ) as trade_mock:
        result = run_autonomous_research_cycle(db_session, test_user, max_symbols=1)

    assert result["status"] == "completed"
    thesis = db_session.query(AgentResearchThesis).one()
    assert thesis.status == "entry_triggered"
    assert thesis.side == "long"
    assert thesis.sleeve == "long"
    assert thesis.strategy_name == "formula_long_momentum"
    assert thesis.entry_target == latest_price
    assert thesis.take_profit_target > thesis.entry_target
    assert thesis.stop_loss_target < thesis.entry_target
    assert thesis.formula_outputs["sleeve"] == "long"
    assert thesis.model_role == "formula"
    assert thesis.llm_model is None
    assert db_session.query(PaperOrder).count() == 1
    position = db_session.query(PaperPosition).one()
    assert position.take_profit == thesis.take_profit_target
    assert position.stop_loss == thesis.stop_loss_target
    assert position.trailing_peak is not None
    assert db_session.query(AgentLesson).filter(AgentLesson.outcome == "paper_buy").count() == 1
    assert db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "thesis_created").count() == 1
    assert db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "paper_order_executed").count() == 1
    thesis_mock.assert_not_called()
    trade_mock.assert_not_called()


def test_autonomous_research_prefers_kraken_ready_asset(db_session, test_user, monkeypatch):
    _seed_recent_prices(db_session, exchange="kraken", count=260, base=200.0)
    _seed_recent_prices(db_session, exchange="coinbase", count=320, base=100.0)
    db_session.add(_profile(test_user.id))
    update_formula_config(
        db_session,
        test_user,
        parameters={"entry_score_floor": 0.1, "long": {"entry_threshold": 0.1}, "short": {"entry_threshold": 0.1}},
    )
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

    with patch("app.services.crew_autonomy.OllamaThesisClient.generate_thesis") as thesis_mock:
        result = run_autonomous_research_cycle(db_session, test_user, max_symbols=1)

    assert result["status"] == "completed"
    thesis = db_session.query(AgentResearchThesis).one()
    assert thesis.exchange == "kraken"
    assert thesis.symbol == "BTC-USD"
    thesis_mock.assert_not_called()


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

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade") as review_mock:
        buy_result = monitor_price_triggers(db_session, test_user)
        duplicate_entry_result = monitor_price_triggers(db_session, test_user)
    assert buy_result["executed"] == 1
    position = db_session.query(PaperPosition).one()
    assert position.take_profit == thesis.take_profit_target
    assert position.stop_loss is not None
    assert position.trailing_peak is not None
    assert db_session.query(PaperOrder).count() == 1
    assert duplicate_entry_result["executed"] == 0
    assert db_session.query(PaperOrder).count() == 1
    review_mock.assert_not_called()

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

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade") as review_mock:
        sell_result = monitor_price_triggers(db_session, test_user)
        review_mock.assert_not_called()
    assert sell_result["executed"] == 1
    assert db_session.query(PaperPosition).count() == 0
    assert db_session.query(PaperOrder).count() == 2
    assert {order.exchange for order in db_session.query(PaperOrder).all()} == {"kraken"}
    assert db_session.query(AgentLesson).filter(AgentLesson.outcome == "take_profit").count() == 1
    assert db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "paper_order_executed").count() == 2


def test_trigger_monitor_shorts_and_covers_on_targets(db_session, test_user, monkeypatch):
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
        strategy_name="formula_quick_short",
        strategy_params={},
        side="short",
        sleeve="short",
        confidence=0.82,
        thesis="Downside formula setup with defined paper short exits.",
        entry_condition="immediate",
        entry_target=latest_price,
        take_profit_target=latest_price - 2,
        stop_loss_target=latest_price + 2,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
        entry_score=0.8,
        formula_inputs={"atr": 1.0},
        formula_outputs={"sleeve": "short", "take_profit": latest_price - 2, "stop_loss": latest_price + 2},
        strategy_version="formula-v1",
    )
    db_session.add(thesis)
    db_session.flush()

    from app.models.backtest import BacktestRun

    recommendation = AgentRecommendation(
        user_id=test_user.id,
        agent_name="Portfolio Manager",
        strategy_name="formula_quick_short",
        exchange="kraken",
        symbol="BTC-USD",
        action="short",
        side="short",
        sleeve="short",
        confidence=0.82,
        thesis="Downside formula setup with defined paper short exits.",
        paper_account_id=account.id,
        status="proposed",
    )
    backtest = BacktestRun(
        user_id=test_user.id,
        name="short-test",
        symbol="BTC-USD",
        exchange="kraken",
        timeframe="1m",
        start=latest_ts - timedelta(days=1),
        end=latest_ts,
        initial_cash=10000,
        fee_rate=0.001,
        slippage_bps=5.0,
        max_position_pct=0.35,
        strategy="formula_quick_short",
        strategy_params={},
        metrics={"total_return_pct": 1, "sharpe_ratio": 1, "sortino_ratio": 1, "sleeve": "short"},
        equity_curve=[],
    )
    db_session.add_all([recommendation, backtest])
    db_session.flush()
    recommendation.backtest_run_id = backtest.id
    thesis.recommendation_id = recommendation.id
    db_session.commit()
    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_TRIGGER_MONITOR_ENABLED", True)

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade") as review_mock:
        short_result = monitor_price_triggers(db_session, test_user)
        assert short_result["executed"] == 1
        position = db_session.query(PaperPosition).one()
        assert position.side == "short"
        assert position.reserved_collateral > 0
        assert position.take_profit == thesis.take_profit_target
        assert position.stop_loss is not None
        assert position.trailing_trough is not None

        new_ts = latest_ts + timedelta(minutes=1)
        cover_price = latest_price - 3
        db_session.add(
            Price(
                exchange="kraken",
                symbol="BTC-USD",
                timestamp=new_ts,
                open=cover_price,
                high=cover_price,
                low=cover_price,
                close=cover_price,
                volume=20,
            )
        )
        status = db_session.query(AssetDataStatus).filter(AssetDataStatus.symbol == "BTC-USD").one()
        status.latest_candle_at = new_ts
        db_session.commit()

        cover_result = monitor_price_triggers(db_session, test_user)
        review_mock.assert_not_called()
    assert cover_result["executed"] == 1
    assert db_session.query(PaperPosition).count() == 0
    assert [order.side.value for order in db_session.query(PaperOrder).order_by(PaperOrder.id).all()] == ["short", "cover"]
    assert db_session.query(AgentLesson).filter(AgentLesson.outcome == "take_profit").count() == 1


def test_trigger_monitor_repairs_orphan_long_position_and_exits_on_take_profit(db_session, test_user, monkeypatch):
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
    position = PaperPosition(
        account_id=account.id,
        exchange="kraken",
        symbol="BTC-USD",
        side="long",
        quantity=10,
        avg_entry_price=latest_price,
        last_price=latest_price,
    )
    db_session.add(position)
    new_ts = latest_ts + timedelta(minutes=1)
    exit_price = latest_price + 6
    db_session.add(
        Price(
            exchange="kraken",
            symbol="BTC-USD",
            timestamp=new_ts,
            open=exit_price,
            high=exit_price,
            low=exit_price,
            close=exit_price,
            volume=20,
        )
    )
    status = db_session.query(AssetDataStatus).filter(AssetDataStatus.symbol == "BTC-USD").one()
    status.latest_candle_at = new_ts
    db_session.commit()

    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    result = monitor_price_triggers(db_session, test_user)

    assert result["repaired"] == 1
    assert result["executed"] == 1
    assert db_session.query(PaperPosition).count() == 0
    assert [order.side.value for order in db_session.query(PaperOrder).order_by(PaperOrder.id).all()] == ["sell"]
    repair = db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "position_exit_repaired").one()
    assert repair.evidence_json["exit_source"] == "formula"
    exit_event = (
        db_session.query(AgentTraceEvent)
        .filter(AgentTraceEvent.event_type == "paper_order_executed", AgentTraceEvent.symbol == "BTC-USD")
        .one()
    )
    assert exit_event.evidence_json["reason_code"] == "orphan_position_closed"


def test_trigger_monitor_repairs_orphan_short_position_and_covers_on_stop_loss(db_session, test_user, monkeypatch):
    latest_price, latest_ts = _seed_recent_prices(db_session, exchange="kraken")
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=9000,
        last_equity=10000,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id)
    db_session.add_all([account, profile])
    db_session.commit()
    db_session.refresh(account)
    profile.ai_paper_account_id = account.id
    position = PaperPosition(
        account_id=account.id,
        exchange="kraken",
        symbol="BTC-USD",
        side="short",
        quantity=10,
        avg_entry_price=latest_price,
        last_price=latest_price,
        reserved_collateral=latest_price * 10,
    )
    db_session.add(position)
    new_ts = latest_ts + timedelta(minutes=1)
    exit_price = latest_price + 5
    db_session.add(
        Price(
            exchange="kraken",
            symbol="BTC-USD",
            timestamp=new_ts,
            open=exit_price,
            high=exit_price,
            low=exit_price,
            close=exit_price,
            volume=20,
        )
    )
    status = db_session.query(AssetDataStatus).filter(AssetDataStatus.symbol == "BTC-USD").one()
    status.latest_candle_at = new_ts
    db_session.commit()

    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    result = monitor_price_triggers(db_session, test_user)

    assert result["repaired"] == 1
    assert result["executed"] == 1
    assert db_session.query(PaperPosition).count() == 0
    assert [order.side.value for order in db_session.query(PaperOrder).order_by(PaperOrder.id).all()] == ["cover"]
    assert db_session.query(AgentLesson).filter(AgentLesson.outcome == "stop_loss").count() == 1


def test_trigger_monitor_blocks_same_symbol_opposite_entry(db_session, test_user, monkeypatch):
    latest_price, latest_ts = _seed_recent_prices(db_session, exchange="kraken")
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=9000,
        last_equity=10000,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id)
    db_session.add_all([account, profile])
    db_session.commit()
    db_session.refresh(account)
    profile.ai_paper_account_id = account.id
    db_session.add(
        PaperPosition(
            account_id=account.id,
            exchange="kraken",
            symbol="BTC-USD",
            side="short",
            quantity=5,
            avg_entry_price=latest_price,
            last_price=latest_price,
            reserved_collateral=latest_price * 5,
            take_profit=latest_price - 10,
            stop_loss=latest_price + 10,
        )
    )
    thesis = AgentResearchThesis(
        user_id=test_user.id,
        account_id=account.id,
        exchange="kraken",
        symbol="BTC-USD",
        strategy_name="formula_long_momentum",
        strategy_params={},
        side="long",
        sleeve="long",
        confidence=0.82,
        thesis="Long formula setup should not hedge over an existing short.",
        entry_condition="immediate",
        entry_target=latest_price,
        take_profit_target=latest_price + 3,
        stop_loss_target=latest_price - 3,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
        entry_score=0.8,
        formula_outputs={"entry_score": 0.8},
        strategy_version="formula-v1",
    )
    db_session.add(thesis)
    db_session.flush()

    from app.models.backtest import BacktestRun

    recommendation = AgentRecommendation(
        user_id=test_user.id,
        agent_name="Portfolio Manager",
        strategy_name="formula_long_momentum",
        exchange="kraken",
        symbol="BTC-USD",
        action="buy",
        side="long",
        sleeve="long",
        confidence=0.82,
        thesis="Long formula setup should not hedge over an existing short.",
        paper_account_id=account.id,
        status="proposed",
    )
    backtest = BacktestRun(
        user_id=test_user.id,
        name="opposite-position-test",
        symbol="BTC-USD",
        exchange="kraken",
        timeframe="1m",
        start=latest_ts - timedelta(days=1),
        end=latest_ts,
        initial_cash=10000,
        fee_rate=0.001,
        slippage_bps=5.0,
        max_position_pct=0.35,
        strategy="formula_long_momentum",
        strategy_params={},
        metrics={"total_return_pct": 1, "sharpe_ratio": 1, "sortino_ratio": 1},
        equity_curve=[],
    )
    db_session.add_all([recommendation, backtest])
    db_session.flush()
    recommendation.backtest_run_id = backtest.id
    thesis.recommendation_id = recommendation.id
    db_session.commit()

    monkeypatch.setattr("app.services.crew_autonomy.settings.CREW_TRIGGER_MONITOR_ENABLED", True)
    result = monitor_price_triggers(db_session, test_user)

    assert result["blocked"] == 1
    assert db_session.query(PaperOrder).count() == 0
    assert db_session.query(PaperPosition).count() == 1
    blocker = db_session.query(AgentTraceEvent).filter(AgentTraceEvent.event_type == "guardrail_blocked").one()
    assert blocker.evidence_json["reason_code"] == "opposite_position_blocked"


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
    assert payload["run_id"] is not None
    assert payload["max_symbols"] == 3
    assert captured["name"] == "celery_worker.tasks.run_crew_research_cycle_for_user"
    assert captured["args"] == [test_user.id]
    assert captured["kwargs"] == {"run_id": payload["run_id"], "max_symbols": 3, "execute_immediate": True}

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
    assert "deterministic formula paper run" in payload["recommended_action"]


def test_research_dry_run_endpoint_returns_service_result(client, auth_headers):
    expected = {"ok": True, "status": "ok", "model": "fast:latest", "symbol": "BTC-USD"}
    with patch("app.routers.crew.dry_run_research_thesis", return_value=expected) as mocked:
        response = client.post("/api/crew/research/dry-run", headers=auth_headers, json={"symbol": "BTC-USD"})

    assert response.status_code == 200
    assert response.json() == expected
    assert mocked.call_args.kwargs["symbol"] == "BTC-USD"


def test_formula_config_endpoint_reads_and_updates(client, auth_headers):
    response = client.get("/api/crew/formula-config", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["authority_mode"] == "approval_required"
    assert payload["parameters"]["entry_score_floor"] == 0.5
    assert payload["parameters"]["atr_length"] == 14

    update_response = client.patch(
        "/api/crew/formula-config",
        headers=auth_headers,
        json={
            "authority_mode": "auto_apply_bounded",
            "parameters": {
                "entry_score_floor": 0.66,
                "atr_length": 21,
                "long": {"target_atr_multiplier": 2.4},
            },
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["authority_mode"] == "auto_apply_bounded"
    assert updated["parameters"]["entry_score_floor"] == 0.66
    assert updated["parameters"]["atr_length"] == 21
    assert updated["parameters"]["long"]["target_atr_multiplier"] == 2.4


def test_formula_suggestion_approve_and_reject_endpoints(client, auth_headers, db_session, test_user):
    config = get_or_create_formula_config(db_session, test_user)
    proposed = deepcopy(config.parameters_json)
    proposed["entry_score_floor"] = 0.57
    suggestion = AgentFormulaSuggestion(
        user_id=test_user.id,
        config_id=config.id,
        status="pending",
        source="deterministic_optimizer",
        proposed_parameters_json=proposed,
        deterministic_evidence_json={"closed_trade_count": 3, "win_rate": 0.25},
        ai_notes="Tighten entries after weak outcomes.",
    )
    db_session.add(suggestion)
    db_session.commit()

    approve_response = client.post(f"/api/crew/formula-suggestions/{suggestion.id}/approve", headers=auth_headers)

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["applied_at"] is not None
    config_response = client.get("/api/crew/formula-config", headers=auth_headers)
    assert config_response.json()["parameters"]["entry_score_floor"] == 0.57

    config = get_or_create_formula_config(db_session, test_user)
    rejected_params = deepcopy(config.parameters_json)
    rejected_params["entry_score_floor"] = 0.59
    rejected = AgentFormulaSuggestion(
        user_id=test_user.id,
        config_id=config.id,
        status="pending",
        source="deterministic_optimizer",
        proposed_parameters_json=rejected_params,
        deterministic_evidence_json={"closed_trade_count": 3, "win_rate": 0.2},
    )
    db_session.add(rejected)
    db_session.commit()

    reject_response = client.post(f"/api/crew/formula-suggestions/{rejected.id}/reject", headers=auth_headers)

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    suggestions = client.get("/api/crew/formula-suggestions", headers=auth_headers).json()
    assert {row["status"] for row in suggestions} >= {"approved", "rejected"}


def test_formula_learning_auto_applies_bounded_suggestion(db_session, test_user):
    update_formula_config(
        db_session,
        test_user,
        authority_mode=AUTHORITY_AUTO_APPLY_BOUNDED,
        parameters={"entry_score_floor": 0.5, "long": {"entry_threshold": 0.5}, "short": {"entry_threshold": 0.5}},
    )
    for idx in range(3):
        db_session.add(
            AgentLesson(
                user_id=test_user.id,
                symbol="BTC-USD",
                strategy_name="formula_long_momentum",
                outcome="stop_loss",
                return_pct=-1.0 - idx,
                confidence=0.7,
                lesson="Closed trade underperformed.",
            )
        )
    db_session.commit()

    suggestion = maybe_create_formula_suggestion(db_session, test_user, source="test_learning")

    assert suggestion is not None
    assert suggestion.status == "auto_applied"
    config = get_or_create_formula_config(db_session, test_user)
    assert config.parameters_json["entry_score_floor"] == 0.52
    assert config.parameters_json["long"]["entry_threshold"] == 0.52
    assert config.parameters_json["short"]["entry_threshold"] == 0.52


def test_research_run_now_returns_visible_queued_run(client, auth_headers, db_session, test_user, monkeypatch):
    db_session.add(_profile(test_user.id, research_enabled=True, trigger_monitor_enabled=True))
    db_session.commit()
    monkeypatch.setattr("app.routers.crew.settings.CREW_RESEARCH_ENABLED", True)
    monkeypatch.setattr(
        "app.routers.crew.runtime_payload",
        lambda profile, role="thesis": {
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
        id = "research-task-queued"

    def fake_send_task(name, args=None, kwargs=None):
        captured["name"] = name
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeTask()

    monkeypatch.setattr("app.routers.crew.celery_app.send_task", fake_send_task)

    response = client.post(
        "/api/crew/research/run-now",
        headers=auth_headers,
        json={"max_symbols": 1, "execute_immediate": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] == "research-task-queued"
    assert payload["max_symbols"] == 1
    assert payload["execute_immediate"] is True
    assert captured["name"] == "celery_worker.tasks.run_crew_research_cycle_for_user"
    assert captured["args"] == [test_user.id]
    assert captured["kwargs"] == {"run_id": payload["run_id"], "max_symbols": 1, "execute_immediate": True}

    run = db_session.query(AgentRun).filter(AgentRun.id == payload["run_id"]).one()
    assert run.status == "queued"
    assert run.summary["progress"] == "queued"
    assert run.summary["task_id"] == "research-task-queued"

    diagnostics = client.get("/api/crew/no-trade-diagnostics", headers=auth_headers).json()
    assert diagnostics["active_research_tasks"][0]["id"] == payload["run_id"]
    assert "Research is running now" in diagnostics["recommended_action"]


def test_autonomous_research_ignores_thesis_model_timeouts(db_session, test_user, monkeypatch):
    for idx, symbol in enumerate(["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]):
        _seed_recent_prices(db_session, symbol=symbol, exchange="kraken", count=260, base=100.0 + idx)
    db_session.add(_profile(test_user.id, thesis_llm_model="llama3.3:70b"))
    update_formula_config(
        db_session,
        test_user,
        parameters={"entry_score_floor": 0.1, "long": {"entry_threshold": 0.1}, "short": {"entry_threshold": 0.1}},
    )
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

    with patch("app.services.crew_autonomy.OllamaThesisClient.generate_thesis") as thesis_mock:
        result = run_autonomous_research_cycle(db_session, test_user, max_symbols=4, execute_immediate=False)

    assert result["stopped_reason"] is None
    run = db_session.query(AgentRun).filter(AgentRun.mode == "autonomous_research").one()
    assert run.summary["stopped_reason"] is None
    assert len(run.selected_symbols) == 4
    assert (
        db_session.query(AgentTraceEvent)
        .filter(AgentTraceEvent.event_type == "research_blocked_model_timeout")
        .count()
        == 0
    )
    thesis_mock.assert_not_called()


def test_trigger_monitor_ignores_trade_model_rejection(db_session, test_user, monkeypatch):
    latest_price, latest_ts = _seed_recent_prices(db_session, exchange="kraken")
    account = PaperAccount(
        user_id=test_user.id,
        name="AI Team Bankroll",
        cash_balance=10000,
        last_equity=10000,
        equity_peak=10000,
        max_position_pct=0.35,
    )
    profile = _profile(test_user.id, trade_cadence_mode="standard", trade_llm_model="trade-checker:latest")
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

    with patch("app.services.crew_autonomy.OllamaTradeDecisionClient.review_trade") as review_mock:
        result = monitor_price_triggers(db_session, test_user)

    assert result["blocked"] == 0
    assert result["executed"] == 1
    assert db_session.query(PaperOrder).count() == 1
    trigger_recommendation = (
        db_session.query(AgentRecommendation)
        .filter(AgentRecommendation.agent_name == "Trigger Monitor")
        .one()
    )
    assert trigger_recommendation.trade_decision_model == FORMULA_ENGINE_MODEL
    assert trigger_recommendation.trade_decision_status == "formula_approved"
    review_mock.assert_not_called()
