from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from database import Base


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AssetDataStatus(Base):
    __tablename__ = "asset_data_status"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_asset_data_status_exchange_symbol"),
    )

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    base_symbol = Column(String(30), nullable=False, index=True)
    status = Column(String(30), nullable=False, index=True, default="warming_up")
    is_supported = Column(Boolean, default=True)
    is_analyzable = Column(Boolean, default=True)
    row_count = Column(Integer, default=0)
    latest_candle_at = Column(DateTime(timezone=True), nullable=True)
    last_backfill_task_id = Column(String(100), nullable=True)
    last_backfill_started_at = Column(DateTime(timezone=True), nullable=True)
    last_backfill_completed_at = Column(DateTime(timezone=True), nullable=True)
    last_backfill_failed_at = Column(DateTime(timezone=True), nullable=True)
    last_failure_reason = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentGuardrailProfile(Base):
    __tablename__ = "agent_guardrail_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_agent_guardrail_profiles_user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    autonomous_enabled = Column(Boolean, default=True)
    research_enabled = Column(Boolean, default=False)
    trigger_monitor_enabled = Column(Boolean, default=False)
    research_interval_seconds = Column(Integer, default=1800)
    max_position_pct = Column(Float, default=0.35)
    max_daily_loss_pct = Column(Float, default=0.10)
    max_open_positions = Column(Integer, default=12)
    max_trades_per_day = Column(Integer, default=40)
    min_data_freshness_seconds = Column(Integer, default=900)
    min_backtest_return_pct = Column(Float, default=0.0)
    min_backtest_sharpe = Column(Float, default=0.0)
    bankroll_reset_drawdown_pct = Column(Float, default=0.95)
    default_starting_bankroll = Column(Float, default=10000.0)
    trade_cadence_mode = Column(String(40), nullable=False, default="aggressive_paper")
    ai_paper_account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=True, index=True)
    allowed_symbols = Column(JSON, default=list)
    default_llm_model = Column(String(255), nullable=True)
    research_llm_model = Column(String(255), nullable=True)
    thesis_llm_model = Column(String(255), nullable=True)
    risk_llm_model = Column(String(255), nullable=True)
    trade_llm_model = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentFormulaConfig(Base):
    __tablename__ = "agent_formula_configs"
    __table_args__ = (
        Index("ix_agent_formula_configs_user_active", "user_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False, default="Formula v1")
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    parameters_json = Column(JSON, default=dict)
    bounds_json = Column(JSON, default=dict)
    authority_mode = Column(String(40), nullable=False, default="approval_required", index=True)
    created_by = Column(String(40), nullable=False, default="system")
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentFormulaSuggestion(Base):
    __tablename__ = "agent_formula_suggestions"
    __table_args__ = (
        Index("ix_agent_formula_suggestions_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    config_id = Column(Integer, ForeignKey("agent_formula_configs.id"), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="pending", index=True)
    source = Column(String(80), nullable=False, default="deterministic_optimizer")
    proposed_parameters_json = Column(JSON, default=dict)
    deterministic_evidence_json = Column(JSON, default=dict)
    ai_notes = Column(Text, nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class ExchangeMarket(Base):
    __tablename__ = "exchange_markets"
    __table_args__ = (
        UniqueConstraint("exchange", "db_symbol", name="uq_exchange_markets_exchange_db_symbol"),
    )

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    ccxt_symbol = Column(String(80), nullable=False, index=True)
    db_symbol = Column(String(80), nullable=False, index=True)
    base = Column(String(30), nullable=False, index=True)
    quote = Column(String(30), nullable=False, index=True)
    spot = Column(Boolean, default=True, index=True)
    active = Column(Boolean, default=True, index=True)
    is_analyzable = Column(Boolean, default=True, index=True)
    min_order_amount = Column(Float, nullable=True)
    min_order_cost = Column(Float, nullable=True)
    precision_json = Column(JSON, default=dict)
    limits_json = Column(JSON, default=dict)
    metadata_json = Column(JSON, default=dict)
    last_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class DataSourceHealth(Base):
    __tablename__ = "data_source_health"
    __table_args__ = (
        UniqueConstraint("source", name="uq_data_source_health_source"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(40), nullable=False, index=True)
    source_type = Column(String(20), nullable=False, default="cex", index=True)
    enabled = Column(Boolean, default=True, index=True)
    websocket_supported = Column(Boolean, default=False)
    rest_supported = Column(Boolean, default=False)
    quote_supported = Column(Boolean, default=False)
    recent_trades_supported = Column(Boolean, default=False)
    ohlcv_supported = Column(Boolean, default=False)
    rate_limit_profile = Column(String(120), nullable=True)
    reconnect_count = Column(Integer, default=0)
    messages_per_second = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    redis_stream_length = Column(Integer, nullable=True)
    redis_pending_messages = Column(Integer, nullable=True)
    writer_lag_seconds = Column(Float, nullable=True)
    writer_batch_latency_ms = Column(Float, nullable=True)
    rows_per_second = Column(Float, nullable=True)
    db_pressure = Column(Float, nullable=True)
    last_telemetry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_event_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class StreamTarget(Base):
    __tablename__ = "stream_targets"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_stream_targets_exchange_symbol"),
        Index("ix_stream_targets_exchange_status_rank", "exchange", "status", "rank"),
    )

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(40), nullable=False, index=True)
    symbol = Column(String(80), nullable=False, index=True)
    base = Column(String(30), nullable=False, index=True)
    quote = Column(String(30), nullable=False, index=True)
    source_type = Column(String(20), nullable=False, default="cex", index=True)
    status = Column(String(30), nullable=False, default="candidate", index=True)
    coverage_tier = Column(String(30), nullable=False, default="ohlcv_only", index=True)
    capacity_state = Column(String(30), nullable=False, default="normal", index=True)
    expected_messages_per_second = Column(Float, nullable=True)
    rank = Column(Integer, nullable=True, index=True)
    score = Column(Float, nullable=False, default=0.0, index=True)
    active = Column(Boolean, default=False, index=True)
    user_preference = Column(String(20), nullable=False, default="neutral", index=True)
    reason = Column(Text, nullable=True)
    score_details_json = Column(JSON, default=dict)
    last_selected_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    __table_args__ = (
        Index("ix_market_quotes_exchange_symbol_timestamp", "exchange", "symbol", "timestamp"),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    exchange = Column(String(40), nullable=False, index=True)
    symbol = Column(String(80), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    receipt_timestamp = Column(DateTime(timezone=True), nullable=True)
    bid = Column(Float, nullable=True)
    ask = Column(Float, nullable=True)
    bid_size = Column(Float, nullable=True)
    ask_size = Column(Float, nullable=True)
    mid = Column(Float, nullable=True)
    spread_bps = Column(Float, nullable=True)
    source = Column(String(40), nullable=True)
    metadata_json = Column(JSON, default=dict)


class DexPool(Base):
    __tablename__ = "dex_pools"
    __table_args__ = (
        UniqueConstraint("source", "chain_id", "pool_address", name="uq_dex_pools_source_chain_pool"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(40), nullable=False, index=True)
    chain_id = Column(String(40), nullable=False, index=True)
    dex_id = Column(String(80), nullable=True, index=True)
    pool_address = Column(String(140), nullable=False, index=True)
    base_symbol = Column(String(40), nullable=True, index=True)
    quote_symbol = Column(String(40), nullable=True, index=True)
    base_token_address = Column(String(140), nullable=True, index=True)
    quote_token_address = Column(String(140), nullable=True, index=True)
    liquidity_usd = Column(Float, nullable=True)
    volume_24h = Column(Float, nullable=True)
    price_usd = Column(Float, nullable=True)
    metadata_json = Column(JSON, default=dict)
    last_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentRecommendation(Base):
    __tablename__ = "agent_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_name = Column(String(100), nullable=False)
    strategy_name = Column(String(100), nullable=False)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    side = Column(String(20), nullable=False, default="long")
    sleeve = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=False)
    thesis = Column(Text, nullable=False)
    risk_notes = Column(Text, nullable=True)
    source_data_timestamp = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("research_snapshots.id"), nullable=True, index=True)
    prediction_id = Column(Integer, ForeignKey("agent_predictions.id"), nullable=True, index=True)
    backtest_run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=True, index=True)
    paper_account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="proposed", index=True)
    execution_reason = Column(Text, nullable=True)
    evidence_json = Column(JSON, default=dict)
    backtest_summary = Column(JSON, default=dict)
    execution_decision = Column(Text, nullable=True)
    model_role = Column(String(40), nullable=True)
    llm_model = Column(String(255), nullable=True)
    trade_decision_model = Column(String(255), nullable=True)
    trade_decision_status = Column(String(40), nullable=True)
    entry_score = Column(Float, nullable=True)
    exit_score = Column(Float, nullable=True)
    formula_inputs = Column(JSON, default=dict)
    formula_outputs = Column(JSON, default=dict)
    strategy_version = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="queued", index=True)
    mode = Column(String(40), nullable=False, default="supervised_auto")
    llm_provider = Column(String(40), nullable=False, default="ollama")
    llm_base_url = Column(String(255), nullable=True)
    llm_model = Column(String(120), nullable=True)
    max_symbols = Column(Integer, nullable=True)
    requested_symbols = Column(JSON, default=list)
    selected_symbols = Column(JSON, default=list)
    error_message = Column(Text, nullable=True)
    summary = Column(JSON, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class ResearchSnapshot(Base):
    __tablename__ = "research_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    price = Column(Float, nullable=True)
    source_data_timestamp = Column(DateTime(timezone=True), nullable=True)
    row_count = Column(Integer, default=0)
    data_status = Column(JSON, default=dict)
    signal = Column(JSON, default=dict)
    snapshot = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now_naive)


class AgentPrediction(Base):
    __tablename__ = "agent_predictions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False, index=True)
    snapshot_id = Column(Integer, ForeignKey("research_snapshots.id"), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    horizon_minutes = Column(Integer, default=240)
    predicted_path = Column(JSON, default=list)
    summary = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)


class AgentAuditLog(Base):
    __tablename__ = "agent_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recommendation_id = Column(Integer, ForeignKey("agent_recommendations.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class AgentTraceEvent(Base):
    __tablename__ = "agent_trace_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True, index=True)
    recommendation_id = Column(Integer, ForeignKey("agent_recommendations.id"), nullable=True, index=True)
    thesis_id = Column(Integer, ForeignKey("agent_research_theses.id"), nullable=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("research_snapshots.id"), nullable=True, index=True)
    role = Column(String(100), nullable=False, default="System")
    exchange = Column(String(20), nullable=True, index=True)
    symbol = Column(String(50), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    status = Column(String(30), nullable=False, index=True)
    public_summary = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    blocker_reason = Column(Text, nullable=True)
    evidence_json = Column(JSON, default=dict)
    prompt = Column(Text, nullable=True)
    raw_model_json = Column(JSON, nullable=True)
    validation_error = Column(Text, nullable=True)
    model_role = Column(String(40), nullable=True)
    llm_model = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class AgentResearchThesis(Base):
    __tablename__ = "agent_research_theses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=True, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("research_snapshots.id"), nullable=True, index=True)
    recommendation_id = Column(Integer, ForeignKey("agent_recommendations.id"), nullable=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    strategy_name = Column(String(100), nullable=False)
    strategy_params = Column(JSON, default=dict)
    side = Column(String(20), nullable=False, default="long")
    sleeve = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=False)
    thesis = Column(Text, nullable=False)
    risk_notes = Column(Text, nullable=True)
    entry_condition = Column(String(30), nullable=False, default="at_or_below")
    entry_target = Column(Float, nullable=True)
    take_profit_target = Column(Float, nullable=True)
    stop_loss_target = Column(Float, nullable=True)
    latest_observed_price = Column(Float, nullable=True)
    status = Column(String(30), nullable=False, default="active", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    lessons_used = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    model_role = Column(String(40), nullable=True)
    llm_model = Column(String(255), nullable=True)
    entry_score = Column(Float, nullable=True)
    exit_score = Column(Float, nullable=True)
    formula_inputs = Column(JSON, default=dict)
    formula_outputs = Column(JSON, default=dict)
    strategy_version = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentModelInvocation(Base):
    __tablename__ = "agent_model_invocations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True, index=True)
    recommendation_id = Column(Integer, ForeignKey("agent_recommendations.id"), nullable=True, index=True)
    thesis_id = Column(Integer, ForeignKey("agent_research_theses.id"), nullable=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("research_snapshots.id"), nullable=True, index=True)
    paper_order_id = Column(Integer, ForeignKey("paper_orders.id"), nullable=True, index=True)
    role = Column(String(100), nullable=False, index=True)
    action_type = Column(String(80), nullable=False, index=True)
    llm_provider = Column(String(40), nullable=False, default="ollama")
    llm_base_url = Column(String(255), nullable=True)
    llm_model = Column(String(255), nullable=False, index=True)
    exchange = Column(String(20), nullable=True, index=True)
    symbol = Column(String(50), nullable=True, index=True)
    status = Column(String(40), nullable=False, index=True)
    timeout_seconds = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    validation_error = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)
    raw_model_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class AgentPortfolioSnapshot(Base):
    __tablename__ = "agent_portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False, index=True)
    cash_balance = Column(Float, default=0.0)
    invested_value = Column(Float, default=0.0)
    equity = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    all_time_pnl = Column(Float, default=0.0)
    current_cycle_pnl = Column(Float, default=0.0)
    drawdown_pct = Column(Float, default=0.0)
    exposure_pct = Column(Float, default=0.0)
    open_positions = Column(Integer, default=0)
    reset_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class AgentBankrollReset(Base):
    __tablename__ = "agent_bankroll_resets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False, index=True)
    reset_number = Column(Integer, nullable=False)
    starting_bankroll = Column(Float, nullable=False)
    equity_before_reset = Column(Float, nullable=False)
    cash_before_reset = Column(Float, default=0.0)
    invested_before_reset = Column(Float, default=0.0)
    drawdown_pct = Column(Float, nullable=False)
    realized_pnl = Column(Float, default=0.0)
    reason = Column(Text, nullable=False)
    lessons = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class AgentLesson(Base):
    __tablename__ = "agent_lessons"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=True, index=True)
    thesis_id = Column(Integer, ForeignKey("agent_research_theses.id"), nullable=True, index=True)
    recommendation_id = Column(Integer, ForeignKey("agent_recommendations.id"), nullable=True, index=True)
    symbol = Column(String(50), nullable=True, index=True)
    strategy_name = Column(String(100), nullable=True, index=True)
    outcome = Column(String(50), nullable=False, index=True)
    return_pct = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    lesson = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, index=True)
