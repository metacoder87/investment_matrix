from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models.research import (
    AgentAuditLog,
    AgentModelInvocation,
    AgentResearchThesis,
    AgentTraceEvent,
    AssetDataStatus,
    AgentPrediction,
    AgentRecommendation,
    AgentRun,
    ResearchSnapshot,
)
from app.models.user import User
from app.routers.auth import get_current_user
from app.models.paper import PaperAccount, PaperPosition
from app.services.crew_autonomy import dry_run_research_thesis, theses_payload, update_thesis
from app.services.crew_execution import (
    attempt_autonomous_execution,
    audit,
    get_or_create_guardrails,
    guardrail_payload,
    recommendation_payload,
)
from app.services.crew_formula_decisions import (
    FORMULA_ENGINE_MODEL,
    approve_formula_suggestion,
    formula_config_payload,
    formula_suggestion_payload,
    get_or_create_formula_config,
    list_formula_suggestions,
    reject_formula_suggestion,
    update_formula_config,
)
from app.services.crew_portfolio import (
    ai_orders,
    ai_positions,
    bankroll_resets,
    equity_curve,
    get_or_create_ai_account,
    lessons,
    portfolio_summary,
    record_portfolio_snapshot,
    reset_bankroll,
    strategy_performance,
)
from app.services.crew_runner import CrewRunOptions, run_crew_cycle, runtime_status
from app.services.crew_trace import trace_event, trace_payload, utc_isoformat
from app.services.crew_models import (
    MODEL_ROUTE_FIELDS,
    apply_model_routing,
    effective_model,
    ensure_model_exists,
    model_routing_payload,
    ollama_models,
    runtime_payload,
    test_model_json,
)
from app.services.market_resolution import primary_exchange
from celery_app import celery_app
from database import get_db


router = APIRouter(prefix="/crew", tags=["AI Crew"])


class GuardrailResponse(BaseModel):
    autonomous_enabled: bool
    research_enabled: bool
    trigger_monitor_enabled: bool
    research_interval_seconds: int
    max_position_pct: float
    max_daily_loss_pct: float
    max_open_positions: int
    max_trades_per_day: int
    min_data_freshness_seconds: int
    min_backtest_return_pct: float
    min_backtest_sharpe: float
    bankroll_reset_drawdown_pct: float
    default_starting_bankroll: float
    trade_cadence_mode: str = "aggressive_paper"
    ai_paper_account_id: Optional[int] = None
    allowed_symbols: list[str]
    model_routing: dict[str, Optional[str]] = Field(default_factory=dict)


class GuardrailUpdate(BaseModel):
    autonomous_enabled: Optional[bool] = None
    research_enabled: Optional[bool] = None
    trigger_monitor_enabled: Optional[bool] = None
    research_interval_seconds: Optional[int] = Field(default=None, ge=60, le=86400)
    max_position_pct: Optional[float] = Field(default=None, gt=0, le=1)
    max_daily_loss_pct: Optional[float] = Field(default=None, gt=0, le=1)
    max_open_positions: Optional[int] = Field(default=None, ge=1, le=100)
    max_trades_per_day: Optional[int] = Field(default=None, ge=1, le=500)
    min_data_freshness_seconds: Optional[int] = Field(default=None, ge=60)
    min_backtest_return_pct: Optional[float] = None
    min_backtest_sharpe: Optional[float] = None
    bankroll_reset_drawdown_pct: Optional[float] = Field(default=None, gt=0, le=1)
    default_starting_bankroll: Optional[float] = Field(default=None, gt=0)
    trade_cadence_mode: Optional[str] = Field(default=None, pattern="^(standard|aggressive_paper)$")
    ai_paper_account_id: Optional[int] = None
    allowed_symbols: Optional[list[str]] = None


class RecommendationCreate(BaseModel):
    agent_name: str
    strategy_name: str
    symbol: str
    exchange: str = Field(default_factory=lambda: settings.PRIMARY_EXCHANGE)
    action: str
    side: str = "long"
    sleeve: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    thesis: str
    risk_notes: Optional[str] = None
    source_data_timestamp: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    backtest_run_id: Optional[int] = None
    paper_account_id: Optional[int] = None
    run_id: Optional[int] = None
    snapshot_id: Optional[int] = None
    prediction_id: Optional[int] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    backtest_summary: dict[str, Any] = Field(default_factory=dict)
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    entry_score: Optional[float] = None
    exit_score: Optional[float] = None
    formula_inputs: dict[str, Any] = Field(default_factory=dict)
    formula_outputs: dict[str, Any] = Field(default_factory=dict)
    strategy_version: Optional[str] = None
    auto_execute: bool = False


class RecommendationResponse(BaseModel):
    id: int
    agent_name: str
    strategy_name: str
    symbol: str
    exchange: str
    action: str
    side: str = "long"
    sleeve: Optional[str] = None
    confidence: float
    thesis: str
    risk_notes: Optional[str] = None
    source_data_timestamp: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    run_id: Optional[int] = None
    snapshot_id: Optional[int] = None
    prediction_id: Optional[int] = None
    backtest_run_id: Optional[int] = None
    paper_account_id: Optional[int] = None
    status: str
    execution_reason: Optional[str] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    backtest_summary: dict[str, Any] = Field(default_factory=dict)
    execution_decision: Optional[str] = None
    model_role: Optional[str] = None
    llm_model: Optional[str] = None
    trade_decision_model: Optional[str] = None
    trade_decision_status: Optional[str] = None
    entry_score: Optional[float] = None
    exit_score: Optional[float] = None
    formula_inputs: dict[str, Any] = Field(default_factory=dict)
    formula_outputs: dict[str, Any] = Field(default_factory=dict)
    strategy_version: Optional[str] = None
    created_at: Optional[datetime] = None


class CrewRunCreate(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    max_symbols: int = Field(default=5, ge=1, le=50)
    auto_execute: bool = True
    paper_account_id: Optional[int] = None


class ThesisUpdate(BaseModel):
    status: Optional[str] = None
    entry_target: Optional[float] = Field(default=None, gt=0)
    take_profit_target: Optional[float] = Field(default=None, gt=0)
    stop_loss_target: Optional[float] = Field(default=None, gt=0)
    expires_at: Optional[datetime] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    thesis: Optional[str] = None
    risk_notes: Optional[str] = None


class ResetRequest(BaseModel):
    reason: str = "Manual reset from AI crew dashboard."
    lessons: Optional[str] = None


class AutonomyUpdate(BaseModel):
    autonomous_enabled: Optional[bool] = None
    research_enabled: Optional[bool] = None
    trigger_monitor_enabled: Optional[bool] = None
    research_interval_seconds: Optional[int] = Field(default=None, ge=60, le=86400)
    max_position_pct: Optional[float] = Field(default=None, gt=0, le=1)
    max_daily_loss_pct: Optional[float] = Field(default=None, gt=0, le=1)
    max_open_positions: Optional[int] = Field(default=None, ge=1, le=100)
    max_trades_per_day: Optional[int] = Field(default=None, ge=1, le=500)
    bankroll_reset_drawdown_pct: Optional[float] = Field(default=None, gt=0, le=1)
    default_starting_bankroll: Optional[float] = Field(default=None, gt=0)
    trade_cadence_mode: Optional[str] = Field(default=None, pattern="^(standard|aggressive_paper)$")
    ai_paper_account_id: Optional[int] = None


class ModelRoutingUpdate(BaseModel):
    default: Optional[str] = None
    research: Optional[str] = None
    thesis: Optional[str] = None
    risk: Optional[str] = None
    trade: Optional[str] = None


class ModelTestRequest(BaseModel):
    role: str = "default"
    model: Optional[str] = None


class ResearchDryRunRequest(BaseModel):
    symbol: Optional[str] = None


class ResearchRunNowRequest(BaseModel):
    max_symbols: Optional[int] = Field(default=None, ge=1, le=10)
    execute_immediate: bool = True


class FormulaConfigUpdate(BaseModel):
    name: Optional[str] = None
    authority_mode: Optional[str] = Field(default=None, pattern="^(approval_required|auto_apply_bounded)$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    bounds: Optional[dict[str, Any]] = None


@router.get("/runtime")
def get_crew_runtime(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    profile = get_or_create_guardrails(db, current_user)
    return runtime_payload(profile)


@router.get("/models")
def get_crew_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    profile = get_or_create_guardrails(db, current_user)
    payload = ollama_models()
    payload["routing"] = model_routing_payload(profile)
    payload["current_model"] = effective_model(profile, "default")
    return payload


@router.patch("/model-routing")
def update_model_routing(
    payload: ModelRoutingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    profile = get_or_create_guardrails(db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    models_payload = ollama_models()
    for role, model in updates.items():
        if role not in MODEL_ROUTE_FIELDS or not model:
            continue
        try:
            ensure_model_exists(model, models_payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    apply_model_routing(profile, updates)
    audit(db, current_user, "model_routing_updated", {"model_routing": model_routing_payload(profile)})
    trace_event(
        db,
        current_user,
        event_type="model_routing_updated",
        status="completed",
        public_summary="Crew model routing was updated.",
        role="System",
        evidence=model_routing_payload(profile),
    )
    db.commit()
    db.refresh(profile)
    return {"routing": model_routing_payload(profile)}


@router.post("/model/test")
def test_crew_model(
    payload: ModelTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    profile = get_or_create_guardrails(db, current_user)
    role = payload.role
    model = payload.model or effective_model(profile, role)
    try:
        ensure_model_exists(model)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result = test_model_json(db, current_user, role=role, model=model)
    trace_event(
        db,
        current_user,
        event_type="model_test_completed" if result["ok"] else "model_test_failed",
        status="completed" if result["ok"] else "blocked",
        public_summary=(
            f"{model} passed the {role} model probe."
            if result["ok"]
            else f"{model} failed the {role} model probe."
        ),
        role="System",
        blocker_reason=None if result["ok"] else result["message"],
        evidence=result,
        model_role=role,
        llm_model=model,
    )
    db.commit()
    return result


@router.post("/research/run-now")
def run_research_now(
    payload: ResearchRunNowRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    profile = get_or_create_guardrails(db, current_user)
    runtime = runtime_payload(profile, role="thesis")
    if not runtime.get("enabled") or not runtime.get("available"):
        raise HTTPException(status_code=409, detail=runtime.get("message", "Crew runtime is not ready."))
    if not settings.CREW_RESEARCH_ENABLED or not profile.research_enabled:
        raise HTTPException(status_code=409, detail="Research is disabled globally or paused for this user.")
    max_symbols = _default_run_now_symbols(profile, payload.max_symbols if payload else None)
    return _queue_research_task(
        db,
        current_user,
        profile,
        max_symbols=max_symbols,
        execute_immediate=payload.execute_immediate if payload else True,
        source="Crew dashboard",
    )


@router.post("/research/dry-run")
def dry_run_research(
    payload: ResearchDryRunRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return dry_run_research_thesis(db, current_user, symbol=payload.symbol if payload else None)


@router.get("/no-trade-diagnostics")
def get_no_trade_diagnostics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return _no_trade_diagnostics(db, current_user)


@router.get("/model-performance")
def get_model_performance(
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    invocations = (
        db.query(AgentModelInvocation)
        .filter(AgentModelInvocation.user_id == current_user.id)
        .order_by(AgentModelInvocation.created_at.desc())
        .limit(limit)
        .all()
    )
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in invocations:
        key = (row.llm_model, row.role)
        entry = grouped.setdefault(
            key,
            {
                "model": row.llm_model,
                "role": row.role,
                "calls": 0,
                "successes": 0,
                "failures": 0,
                "timeouts": 0,
                "approved": 0,
                "rejected": 0,
                "validation_failures": 0,
                "avg_latency_ms": 0,
                "theses_created": 0,
                "trades_approved": 0,
                "trades_rejected": 0,
                "timeout_rate_pct": 0,
                "latest_status": None,
                "latest_error": None,
                "latest_validation_error": None,
                "last_used_at": None,
            },
        )
        entry["calls"] += 1
        if entry["latest_status"] is None:
            entry["latest_status"] = row.status
            entry["latest_error"] = row.error_message
            entry["latest_validation_error"] = row.validation_error
        if row.status in {"success", "approved"}:
            entry["successes"] += 1
        elif row.status in {"timeout"}:
            entry["timeouts"] += 1
            entry["failures"] += 1
        elif row.status in {"rejected"}:
            entry["rejected"] += 1
        else:
            entry["failures"] += 1
        if row.status == "approved":
            entry["approved"] += 1
            if row.action_type == "trade_decision":
                entry["trades_approved"] += 1
        if row.status == "rejected" and row.action_type == "trade_decision":
            entry["trades_rejected"] += 1
        if row.status == "validation_failed":
            entry["validation_failures"] += 1
        if row.action_type == "research_thesis" and row.status in {"success", "approved"}:
            entry["theses_created"] += 1
        if row.latency_ms is not None:
            entry["avg_latency_ms"] += int(row.latency_ms)
        created_at = utc_isoformat(row.created_at)
        if created_at and (entry["last_used_at"] is None or created_at > entry["last_used_at"]):
            entry["last_used_at"] = created_at
    results = []
    for entry in grouped.values():
        latency_count = sum(
            1
            for row in invocations
            if row.llm_model == entry["model"] and row.role == entry["role"] and row.latency_ms is not None
        )
        if latency_count:
            entry["avg_latency_ms"] = round(entry["avg_latency_ms"] / latency_count)
        entry["success_rate_pct"] = round((entry["successes"] / entry["calls"]) * 100, 1) if entry["calls"] else 0
        entry["timeout_rate_pct"] = round((entry["timeouts"] / entry["calls"]) * 100, 1) if entry["calls"] else 0
        results.append(entry)
    return sorted(results, key=lambda item: (item["role"], item["model"]))


@router.get("/formula-config")
def get_formula_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    config = get_or_create_formula_config(db, current_user)
    db.commit()
    return formula_config_payload(config)


@router.patch("/formula-config")
def patch_formula_config(
    payload: FormulaConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        config = update_formula_config(
            db,
            current_user,
            name=payload.name,
            authority_mode=payload.authority_mode,
            parameters=payload.parameters if payload.parameters else None,
            bounds=payload.bounds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(db, current_user, "formula_config_updated", {"formula_config": formula_config_payload(config)})
    trace_event(
        db,
        current_user,
        event_type="formula_config_updated",
        status="completed",
        public_summary="Deterministic formula settings were updated.",
        role="System",
        evidence=formula_config_payload(config),
        model_role="formula",
        llm_model=None,
    )
    db.commit()
    db.refresh(config)
    return formula_config_payload(config)


@router.get("/formula-suggestions")
def get_formula_suggestions(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    get_or_create_formula_config(db, current_user)
    db.commit()
    return list_formula_suggestions(db, current_user, limit=limit)


@router.post("/formula-suggestions/{suggestion_id}/approve")
def approve_formula_suggestion_route(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    suggestion = approve_formula_suggestion(db, current_user, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Formula suggestion not found.")
    payload = formula_suggestion_payload(suggestion)
    audit(db, current_user, "formula_suggestion_approved", {"suggestion": payload})
    trace_event(
        db,
        current_user,
        event_type="formula_suggestion_approved",
        status="completed",
        public_summary="Formula suggestion was approved and applied.",
        role="System",
        evidence=payload,
        model_role="formula",
        llm_model=None,
    )
    db.commit()
    return payload


@router.post("/formula-suggestions/{suggestion_id}/reject")
def reject_formula_suggestion_route(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    suggestion = reject_formula_suggestion(db, current_user, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Formula suggestion not found.")
    payload = formula_suggestion_payload(suggestion)
    audit(db, current_user, "formula_suggestion_rejected", {"suggestion": payload})
    trace_event(
        db,
        current_user,
        event_type="formula_suggestion_rejected",
        status="completed",
        public_summary="Formula suggestion was rejected.",
        role="System",
        evidence=payload,
        model_role="formula",
        llm_model=None,
    )
    db.commit()
    return payload


@router.post("/pause", response_model=GuardrailResponse)
def pause_autonomous_paper(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _pause_bot_profile(db, current_user, reason="Manual pause from AI crew desk.")
    return GuardrailResponse(**guardrail_payload(profile))


@router.post("/autonomy/start")
def start_autonomous_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    runtime = runtime_status()
    if not runtime.get("enabled") or not runtime.get("available"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": runtime.get("message", "Crew runtime is not ready."),
                "bot_state": "setup_needed",
            },
        )
    if not settings.CREW_RESEARCH_ENABLED or not settings.CREW_TRIGGER_MONITOR_ENABLED:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Global Crew schedulers are disabled. Set CREW_RESEARCH_ENABLED=true "
                    "and CREW_TRIGGER_MONITOR_ENABLED=true, then restart the stack."
                ),
                "bot_state": "setup_needed",
            },
        )

    exchange = primary_exchange()
    ready_assets = _ready_primary_asset_count(db, exchange)
    if ready_assets <= 0:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"No {exchange.upper()} assets are ready for AI research yet. "
                    f"Backfill {exchange.upper()} assets first."
                ),
                "bot_state": "setup_needed",
                "backfill_path": f"/api/backfill/universe?exchange={exchange}",
            },
        )

    profile = get_or_create_guardrails(db, current_user)
    account = get_or_create_ai_account(db, current_user)
    profile.ai_paper_account_id = account.id
    profile.autonomous_enabled = True
    profile.research_enabled = True
    profile.trigger_monitor_enabled = True
    profile.research_interval_seconds = profile.research_interval_seconds or settings.CREW_RESEARCH_INTERVAL_SECONDS
    profile.trade_cadence_mode = profile.trade_cadence_mode or "aggressive_paper"
    account.max_position_pct = min(float(account.max_position_pct or 1.0), float(profile.max_position_pct or 0.35))
    audit(
        db,
        current_user,
        "autonomous_bot_started",
        {
            "account_id": account.id,
            "primary_exchange": exchange,
            "ready_assets": ready_assets,
            "runtime": runtime,
            "trade_cadence_mode": profile.trade_cadence_mode,
        },
    )
    trace_event(
        db,
        current_user,
        event_type="autonomous_bot_started",
        status="running",
        public_summary=f"Autonomous paper bot started on {exchange.upper()}.",
        role="Portfolio Manager",
        exchange=exchange,
        rationale="The user enabled per-user autonomous research, trigger monitoring, and paper-only execution.",
        evidence={"ready_assets": ready_assets, "account_id": account.id, "runtime": runtime},
    )
    db.commit()
    db.refresh(profile)

    queued = _queue_research_task(
        db,
        current_user,
        profile,
        max_symbols=_default_run_now_symbols(profile, None),
        execute_immediate=True,
        source="bot start",
    )
    return {
        "status": "started",
        "bot_state": "running",
        "primary_exchange": exchange,
        "ready_assets": ready_assets,
        "account_id": account.id,
        "research_task_id": queued["task_id"],
        "run_id": queued["run_id"],
        "max_symbols": queued["max_symbols"],
        "guardrails": guardrail_payload(profile),
    }


@router.post("/autonomy/pause", response_model=GuardrailResponse)
def pause_autonomous_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _pause_bot_profile(db, current_user, reason="Manual pause from AI crew desk.")
    return GuardrailResponse(**guardrail_payload(profile))


@router.post("/runs")
def create_crew_run(
    payload: CrewRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = run_crew_cycle(
        db,
        current_user,
        CrewRunOptions(
            symbols=payload.symbols,
            max_symbols=payload.max_symbols,
            auto_execute=payload.auto_execute,
            paper_account_id=payload.paper_account_id,
        ),
    )
    return _run_detail(db, current_user, run.id)


@router.get("/runs")
def list_crew_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    rows = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == current_user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_run_payload(row) for row in rows]


@router.get("/runs/{run_id}")
def get_crew_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return _run_detail(db, current_user, run_id)


@router.post("/runs/{run_id}/cancel")
def cancel_crew_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == current_user.id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Crew run not found.")
    if run.status in {"queued", "running"}:
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
        audit(db, current_user, "crew_run_cancelled", {"run_id": run.id})
        db.commit()
        db.refresh(run)
    return _run_detail(db, current_user, run.id)


@router.get("/guardrails", response_model=GuardrailResponse)
def get_guardrails(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = get_or_create_guardrails(db, current_user)
    db.commit()
    return GuardrailResponse(**guardrail_payload(profile))


@router.patch("/guardrails", response_model=GuardrailResponse)
def update_guardrails(
    payload: GuardrailUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = get_or_create_guardrails(db, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "allowed_symbols" and value is not None:
            value = [symbol.strip().upper().replace("/", "-") for symbol in value if symbol.strip()]
        setattr(profile, field, value)
    audit(db, current_user, "guardrails_updated", {"guardrails": guardrail_payload(profile)})
    db.commit()
    db.refresh(profile)
    return GuardrailResponse(**guardrail_payload(profile))


@router.patch("/autonomy", response_model=GuardrailResponse)
def update_autonomy(
    payload: AutonomyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = get_or_create_guardrails(db, current_user)
    data = payload.model_dump(exclude_unset=True)
    account_id = data.pop("ai_paper_account_id", None)
    if account_id is not None:
        account = db.query(PaperAccount).filter(PaperAccount.id == account_id, PaperAccount.user_id == current_user.id).first()
        if not account:
            raise HTTPException(status_code=404, detail="AI paper account not found.")
        profile.ai_paper_account_id = account.id
    for field, value in data.items():
        setattr(profile, field, value)
    account = get_or_create_ai_account(db, current_user)
    account.max_position_pct = min(float(account.max_position_pct or 1.0), float(profile.max_position_pct or 0.35))
    audit(db, current_user, "autonomy_settings_updated", {"guardrails": guardrail_payload(profile)})
    db.commit()
    db.refresh(profile)
    return GuardrailResponse(**guardrail_payload(profile))


@router.get("/portfolio/summary")
def get_portfolio_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    summary = portfolio_summary(db, current_user)
    record_portfolio_snapshot(db, current_user)
    db.commit()
    return summary


@router.get("/portfolio/equity")
def get_portfolio_equity(
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return equity_curve(db, current_user, limit=limit)


@router.get("/portfolio/positions")
def get_portfolio_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    positions = ai_positions(db, current_user)
    db.commit()
    return positions


@router.get("/portfolio/orders")
def get_portfolio_orders(
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return ai_orders(db, current_user, limit=limit)


@router.get("/strategies/performance")
def get_strategy_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return strategy_performance(db, current_user)


@router.get("/theses")
def list_theses(
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return theses_payload(db, current_user, limit=limit)


@router.patch("/theses/{thesis_id}")
def patch_thesis(
    thesis_id: int,
    payload: ThesisUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    thesis = update_thesis(db, current_user, thesis_id, payload.model_dump(exclude_unset=True))
    if not thesis:
        raise HTTPException(status_code=404, detail="Research thesis not found.")
    return next(item for item in theses_payload(db, current_user, limit=500) if item["id"] == thesis.id)


@router.get("/resets")
def list_resets(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return bankroll_resets(db, current_user, limit=limit)


@router.post("/resets")
def create_reset(
    payload: ResetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    reset = reset_bankroll(db, current_user, reason=payload.reason, lessons=payload.lessons)
    db.commit()
    return {
        "id": reset.id,
        "reset_number": reset.reset_number,
        "starting_bankroll": reset.starting_bankroll,
        "equity_before_reset": reset.equity_before_reset,
        "drawdown_pct": reset.drawdown_pct,
        "reason": reset.reason,
        "lessons": reset.lessons,
        "created_at": utc_isoformat(reset.created_at),
    }


@router.get("/lessons")
def list_lessons(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return lessons(db, current_user, limit=limit)


@router.get("/recommendations", response_model=list[RecommendationResponse])
def list_recommendations(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(AgentRecommendation)
        .filter(AgentRecommendation.user_id == current_user.id)
        .order_by(AgentRecommendation.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_recommendation_response(row) for row in rows]


@router.post("/recommendations", response_model=RecommendationResponse)
def create_recommendation(
    payload: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recommendation = AgentRecommendation(
        user_id=current_user.id,
        agent_name=payload.agent_name.strip(),
        strategy_name=payload.strategy_name.strip(),
        exchange=payload.exchange.strip().lower(),
        symbol=payload.symbol.strip().upper().replace("/", "-"),
        action=payload.action.strip().lower(),
        side=payload.side.strip().lower(),
        sleeve=payload.sleeve.strip().lower() if payload.sleeve else None,
        confidence=payload.confidence,
        thesis=payload.thesis,
        risk_notes=payload.risk_notes,
        source_data_timestamp=payload.source_data_timestamp,
        expires_at=payload.expires_at,
        run_id=payload.run_id,
        snapshot_id=payload.snapshot_id,
        prediction_id=payload.prediction_id,
        backtest_run_id=payload.backtest_run_id,
        paper_account_id=payload.paper_account_id,
        status="proposed",
        evidence_json=payload.evidence,
        backtest_summary=payload.backtest_summary,
        entry_score=payload.entry_score,
        exit_score=payload.exit_score,
        formula_inputs=payload.formula_inputs or {},
        formula_outputs=payload.formula_outputs or {},
        strategy_version=payload.strategy_version,
    )
    db.add(recommendation)
    db.flush()
    audit(
        db,
        current_user,
        "recommendation_created",
        payload.model_dump(mode="json"),
        recommendation_id=recommendation.id,
    )

    if payload.auto_execute:
        attempt_autonomous_execution(db, current_user, recommendation, payload.strategy_params)

    db.commit()
    db.refresh(recommendation)
    return _recommendation_response(recommendation)


@router.post("/recommendations/{recommendation_id}/execute-paper", response_model=RecommendationResponse)
def execute_recommendation(
    recommendation_id: int,
    strategy_params: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recommendation = (
        db.query(AgentRecommendation)
        .filter(AgentRecommendation.id == recommendation_id, AgentRecommendation.user_id == current_user.id)
        .first()
    )
    if not recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    attempt_autonomous_execution(db, current_user, recommendation, strategy_params or {})
    db.commit()
    db.refresh(recommendation)
    return _recommendation_response(recommendation)


@router.get("/audit")
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    rows = (
        db.query(AgentAuditLog)
        .filter(AgentAuditLog.user_id == current_user.id)
        .order_by(AgentAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "recommendation_id": row.recommendation_id,
            "event_type": row.event_type,
            "payload": row.payload or {},
            "created_at": utc_isoformat(row.created_at),
        }
        for row in rows
    ]


@router.get("/activity")
def list_activity(
    limit: int = Query(default=200, ge=1, le=500),
    debug: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    rows = (
        db.query(AgentTraceEvent)
        .filter(AgentTraceEvent.user_id == current_user.id)
        .order_by(AgentTraceEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [trace_payload(row, debug=debug) for row in rows]


@router.get("/runs/{run_id}/activity")
def list_run_activity(
    run_id: int,
    limit: int = Query(default=200, ge=1, le=500),
    debug: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == current_user.id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Crew run not found.")
    rows = (
        db.query(AgentTraceEvent)
        .filter(AgentTraceEvent.user_id == current_user.id, AgentTraceEvent.run_id == run.id)
        .order_by(AgentTraceEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [trace_payload(row, debug=debug) for row in rows]


def _ready_primary_asset_count(db: Session, exchange: str) -> int:
    return (
        db.query(AssetDataStatus)
        .filter(
            AssetDataStatus.exchange == exchange,
            AssetDataStatus.status == "ready",
            AssetDataStatus.is_analyzable.is_(True),
            AssetDataStatus.row_count >= 50,
        )
        .count()
    )


def _default_run_now_symbols(profile, requested: int | None) -> int:
    if requested is not None:
        return max(1, min(int(requested), 10))
    if getattr(profile, "trade_cadence_mode", None) == "aggressive_paper":
        return 3
    return max(1, min(int(settings.CREW_MAX_SYMBOLS_PER_RUN or 3), 10))


def _queue_research_task(
    db: Session,
    current_user: User,
    profile,
    *,
    max_symbols: int,
    execute_immediate: bool,
    source: str,
) -> dict:
    thesis_model = FORMULA_ENGINE_MODEL
    formula_config = formula_config_payload(get_or_create_formula_config(db, current_user))
    run = AgentRun(
        user_id=current_user.id,
        status="queued",
        mode="autonomous_research",
        llm_provider="formula",
        llm_base_url=None,
        llm_model=thesis_model,
        max_symbols=max_symbols,
        requested_symbols=[],
        selected_symbols=[],
        summary={
            "agents": ["Market Data Auditor", "Technical Analyst", "Risk Manager", "Backtest Analyst", "Portfolio Manager"],
            "mode": "autonomous_research",
            "progress": "queued",
            "execute_immediate": execute_immediate,
            "source": source,
            "formula_config": {
                "id": formula_config["id"],
                "authority_mode": formula_config["authority_mode"],
                "entry_score_floor": formula_config["parameters"].get("entry_score_floor"),
                "version": formula_config["parameters"].get("version"),
            },
        },
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    task = celery_app.send_task(
        "celery_worker.tasks.run_crew_research_cycle_for_user",
        args=[current_user.id],
        kwargs={"run_id": run.id, "max_symbols": max_symbols, "execute_immediate": execute_immediate},
    )
    run.summary = {**(run.summary or {}), "task_id": task.id}
    trace_event(
        db,
        current_user,
        event_type="research_queued",
        status="running",
        public_summary=f"Immediate research cycle queued from {source}.",
        role="Market Data Auditor",
        run_id=run.id,
        evidence={
            "reason_code": "research_queued",
            "task_id": task.id,
            "run_id": run.id,
            "max_symbols": max_symbols,
            "execute_immediate": execute_immediate,
            "formula_config": formula_config,
        },
        model_role="formula",
        llm_model=thesis_model,
    )
    db.commit()
    db.refresh(run)
    return {
        "status": "queued",
        "run_id": run.id,
        "task_id": task.id,
        "max_symbols": max_symbols,
        "execute_immediate": execute_immediate,
        "formula_config": formula_config,
    }


def _no_trade_diagnostics(db: Session, current_user: User) -> dict[str, Any]:
    profile = get_or_create_guardrails(db, current_user)
    runtime = runtime_payload(profile, role="thesis")
    active_thesis_count = (
        db.query(AgentResearchThesis)
        .filter(
            AgentResearchThesis.user_id == current_user.id,
            AgentResearchThesis.status.in_(("active", "entry_triggered")),
        )
        .count()
    )
    latest_run = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == current_user.id, AgentRun.mode.in_(("autonomous_research", "research_dry_run")))
        .order_by(AgentRun.created_at.desc())
        .first()
    )
    candidate_research_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.user_id == current_user.id,
            AgentRun.mode == "autonomous_research",
            AgentRun.status.in_(("queued", "running")),
        )
        .order_by(AgentRun.created_at.desc())
        .all()
    )
    active_research_runs = [
        row
        for row in candidate_research_runs
        if not _research_run_looks_stale(row, now=datetime.now(timezone.utc))
    ]
    stale_research_runs = [
        row
        for row in candidate_research_runs
        if _research_run_looks_stale(row, now=datetime.now(timezone.utc))
    ]
    latest_formula_snapshot = (
        db.query(ResearchSnapshot)
        .filter(ResearchSnapshot.user_id == current_user.id)
        .order_by(ResearchSnapshot.created_at.desc())
        .first()
    )
    latest_failure = (
        db.query(AgentModelInvocation)
        .filter(
            AgentModelInvocation.user_id == current_user.id,
            AgentModelInvocation.status.notin_(("success", "approved")),
        )
        .order_by(AgentModelInvocation.created_at.desc())
        .first()
    )
    latest_blocker = (
        db.query(AgentTraceEvent)
        .filter(
            AgentTraceEvent.user_id == current_user.id,
            AgentTraceEvent.blocker_reason.isnot(None),
        )
        .order_by(AgentTraceEvent.created_at.desc())
        .first()
    )
    paper_account = None
    if profile.ai_paper_account_id:
        paper_account = (
            db.query(PaperAccount)
            .filter(PaperAccount.id == profile.ai_paper_account_id, PaperAccount.user_id == current_user.id)
            .first()
        )
    open_positions: list[PaperPosition] = []
    if paper_account is not None:
        open_positions = (
            db.query(PaperPosition)
            .filter(PaperPosition.account_id == paper_account.id, PaperPosition.quantity > 0)
            .order_by(PaperPosition.updated_at.desc())
            .all()
        )
    unmanaged_positions = [
        position for position in open_positions if position.take_profit is None or position.stop_loss is None
    ]
    latest_repaired_position = (
        db.query(AgentTraceEvent)
        .filter(
            AgentTraceEvent.user_id == current_user.id,
            AgentTraceEvent.event_type == "position_exit_repaired",
        )
        .order_by(AgentTraceEvent.created_at.desc())
        .first()
    )

    blockers: list[str] = []
    if not runtime.get("enabled") or not runtime.get("available"):
        blockers.append(runtime.get("message") or "Crew runtime is unavailable.")
    if not settings.CREW_RESEARCH_ENABLED:
        blockers.append("Global research scheduler is disabled.")
    if not settings.CREW_TRIGGER_MONITOR_ENABLED:
        blockers.append("Global trigger monitor is disabled.")
    if not profile.research_enabled:
        blockers.append("Research is paused for this user.")
    if not profile.trigger_monitor_enabled:
        blockers.append("Trigger monitoring is paused for this user.")
    if not profile.autonomous_enabled:
        blockers.append("Autonomous paper execution is paused.")

    if runtime.get("ai_notes_enabled") and latest_failure is not None and latest_failure.status == "timeout":
        blockers.append(
            f"{latest_failure.role} model {latest_failure.llm_model} timed out after "
            f"{latest_failure.timeout_seconds or settings.CREW_LLM_TIMEOUT_SECONDS} seconds."
        )

    latest_summary = latest_run.summary if latest_run is not None and isinstance(latest_run.summary, dict) else {}
    if latest_summary.get("stopped_reason"):
        blockers.append(str(latest_summary["stopped_reason"]))
    if active_research_runs:
        blockers.append("Research is currently running; waiting for formula thesis and paper execution results.")
    if stale_research_runs:
        blockers.append("A previous research run appears interrupted; queue a fresh formula-first paper run.")
    if unmanaged_positions:
        blockers.append(f"{len(unmanaged_positions)} open paper position(s) need exit-plan repair.")
    if not active_research_runs and latest_run is not None and latest_summary.get("theses_created") == 0:
        blockers.append("Latest research cycle created zero active theses.")
    if active_thesis_count == 0 and not active_research_runs and not open_positions:
        blockers.append("No active thesis is waiting on an entry target and no open paper positions need exit monitoring.")
    if latest_blocker is not None and latest_blocker.blocker_reason:
        blockers.append(latest_blocker.blocker_reason)

    deduped_blockers: list[str] = []
    for blocker in blockers:
        if blocker and blocker not in deduped_blockers:
            deduped_blockers.append(blocker)

    if active_research_runs:
        recommended_action = "Research is running now; watch the Decision Log for formula thesis, backtest, and paper order events."
    elif stale_research_runs:
        recommended_action = "Queue Run paper trade now to replace the interrupted research run with a fresh visible run."
    elif unmanaged_positions and profile.trigger_monitor_enabled:
        recommended_action = "Trigger monitoring will repair open position exit targets on the next tick, then manage take-profit and stop-loss exits."
    elif unmanaged_positions:
        recommended_action = "Enable trigger monitoring so open paper positions can be repaired and exit-managed."
    elif runtime.get("ai_notes_enabled") and latest_failure is not None and latest_failure.status == "timeout":
        recommended_action = (
            "Optional AI notes are timing out; formula trading can continue while you select a faster local model."
        )
    elif active_thesis_count == 0:
        recommended_action = "Queue a deterministic formula paper run so the engine can create a thesis when a sleeve clears the entry floor."
    elif not profile.autonomous_enabled or not profile.trigger_monitor_enabled:
        recommended_action = "Start the bot or enable trigger monitoring so active theses can be monitored."
    else:
        recommended_action = "The trigger monitor is waiting for entry, take-profit, or stop-loss prices to cross."

    return {
        "active_thesis_count": active_thesis_count,
        "active_research_tasks": [_run_payload(row) for row in active_research_runs],
        "latest_run": _run_payload(latest_run) if latest_run else None,
        "latest_research_run": _run_payload(latest_run) if latest_run else None,
        "latest_formula_candidate": _formula_candidate_payload(latest_formula_snapshot),
        "latest_execution_blocker": trace_payload(latest_blocker) if latest_blocker else None,
        "open_position_count": len(open_positions),
        "unmanaged_position_count": len(unmanaged_positions),
        "latest_repaired_position": trace_payload(latest_repaired_position) if latest_repaired_position else None,
        "latest_model_failure": _model_invocation_payload(latest_failure) if latest_failure else None,
        "latest_blocker": trace_payload(latest_blocker) if latest_blocker else None,
        "blockers": deduped_blockers[:10],
        "recommended_action": recommended_action,
        "runtime": runtime,
        "model_routing": model_routing_payload(profile),
    }


def _pause_bot_profile(db: Session, current_user: User, *, reason: str):
    profile = get_or_create_guardrails(db, current_user)
    profile.autonomous_enabled = False
    profile.research_enabled = False
    profile.trigger_monitor_enabled = False
    audit(db, current_user, "autonomous_bot_paused", {"reason": reason})
    trace_event(
        db,
        current_user,
        event_type="autonomous_bot_paused",
        status="paused",
        public_summary="Autonomous research, trigger monitoring, and paper execution were paused.",
        role="Portfolio Manager",
        blocker_reason=reason,
    )
    db.commit()
    db.refresh(profile)
    return profile


def _model_invocation_payload(row: AgentModelInvocation) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "role": row.role,
        "action_type": row.action_type,
        "model": row.llm_model,
        "status": row.status,
        "timeout_seconds": row.timeout_seconds,
        "latency_ms": row.latency_ms,
        "error_message": row.error_message,
        "validation_error": row.validation_error,
        "response_summary": row.response_summary,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "created_at": utc_isoformat(row.created_at),
        "completed_at": utc_isoformat(row.completed_at),
    }


def _formula_candidate_payload(row: ResearchSnapshot | None) -> dict[str, Any] | None:
    if row is None:
        return None
    signal = row.signal or {}
    metrics = signal.get("formula_metrics") if isinstance(signal, dict) else None
    if not metrics and isinstance(row.snapshot, dict):
        metrics = row.snapshot.get("formula_metrics")
    if not isinstance(metrics, dict):
        return None
    long_metrics = metrics.get("long") if isinstance(metrics.get("long"), dict) else {}
    short_metrics = metrics.get("short") if isinstance(metrics.get("short"), dict) else {}
    long_score = float(long_metrics.get("long_entry_score") or 0.0)
    short_score = float(short_metrics.get("short_entry_score") or 0.0)
    side = "short" if short_score > long_score else "long"
    return {
        "snapshot_id": row.id,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "price": row.price,
        "side": side,
        "entry_score": max(long_score, short_score),
        "long_entry_score": long_score,
        "short_entry_score": short_score,
        "source_data_timestamp": utc_isoformat(row.source_data_timestamp),
        "created_at": utc_isoformat(row.created_at),
    }


def _research_run_looks_stale(run: AgentRun, *, now: datetime) -> bool:
    if run.status not in {"queued", "running"}:
        return False
    summary = run.summary if isinstance(run.summary, dict) else {}
    checkpoint = _parse_datetime(summary.get("heartbeat_at"))
    checkpoint = checkpoint or _as_aware_datetime(run.updated_at)
    checkpoint = checkpoint or _as_aware_datetime(run.started_at)
    checkpoint = checkpoint or _as_aware_datetime(run.created_at)
    if checkpoint is None:
        return False
    age_seconds = (now - checkpoint).total_seconds()
    if run.status == "queued":
        return age_seconds > max(1800, int(settings.CREW_RESEARCH_INTERVAL_SECONDS or 1800))
    return age_seconds > max(900, int(settings.CREW_LLM_TIMEOUT_SECONDS or 60) * 3)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_aware_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _run_payload(run: AgentRun) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "llm_provider": run.llm_provider,
        "llm_model": run.llm_model,
        "max_symbols": run.max_symbols,
        "requested_symbols": run.requested_symbols or [],
        "selected_symbols": run.selected_symbols or [],
        "error_message": run.error_message,
        "summary": run.summary or {},
        "started_at": utc_isoformat(run.started_at),
        "completed_at": utc_isoformat(run.completed_at),
        "created_at": utc_isoformat(run.created_at),
    }


def _run_detail(db: Session, current_user: User, run_id: int) -> dict:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == current_user.id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Crew run not found.")
    snapshots = (
        db.query(ResearchSnapshot)
        .filter(ResearchSnapshot.run_id == run.id, ResearchSnapshot.user_id == current_user.id)
        .order_by(ResearchSnapshot.created_at.asc())
        .all()
    )
    predictions = (
        db.query(AgentPrediction)
        .filter(AgentPrediction.run_id == run.id, AgentPrediction.user_id == current_user.id)
        .order_by(AgentPrediction.created_at.asc())
        .all()
    )
    recommendations = (
        db.query(AgentRecommendation)
        .filter(AgentRecommendation.run_id == run.id, AgentRecommendation.user_id == current_user.id)
        .order_by(AgentRecommendation.created_at.asc())
        .all()
    )
    audit_rows = (
        db.query(AgentAuditLog)
        .filter(AgentAuditLog.user_id == current_user.id)
        .order_by(AgentAuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    detail = _run_payload(run)
    detail.update(
        {
            "snapshots": [_snapshot_payload(row) for row in snapshots],
            "predictions": [_prediction_payload(row) for row in predictions],
            "recommendations": [_recommendation_response(row).model_dump(mode="json") for row in recommendations],
            "audit": [
                {
                    "id": row.id,
                    "recommendation_id": row.recommendation_id,
                    "event_type": row.event_type,
                    "payload": row.payload or {},
                    "created_at": utc_isoformat(row.created_at),
                }
                for row in audit_rows
                if (row.payload or {}).get("run_id") == run.id
                or row.recommendation_id in {rec.id for rec in recommendations}
            ],
        }
    )
    return detail


def _snapshot_payload(row: ResearchSnapshot) -> dict:
    return {
        "id": row.id,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "price": row.price,
        "source_data_timestamp": utc_isoformat(row.source_data_timestamp),
        "row_count": row.row_count,
        "data_status": row.data_status or {},
        "signal": row.signal or {},
        "snapshot": row.snapshot or {},
        "created_at": utc_isoformat(row.created_at),
    }


def _prediction_payload(row: AgentPrediction) -> dict:
    return {
        "id": row.id,
        "snapshot_id": row.snapshot_id,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "horizon_minutes": row.horizon_minutes,
        "predicted_path": row.predicted_path or [],
        "summary": row.summary,
        "confidence": row.confidence,
        "created_at": utc_isoformat(row.created_at),
    }


def _recommendation_response(row: AgentRecommendation) -> RecommendationResponse:
    return RecommendationResponse(**recommendation_payload(row))
