from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models.paper import PaperOrder, PaperOrderSide, PaperPosition
from app.models.research import (
    AgentLesson,
    AgentRecommendation,
    AgentResearchThesis,
    AgentRun,
    AssetDataStatus,
)
from app.models.user import User
from app.services.crew_execution import (
    audit,
    check_guardrails,
    execute_price_trigger_order,
    get_or_create_guardrails,
)
from app.services.crew_formula_decisions import (
    FORMULA_ENGINE_MODEL,
    formula_decision_from_snapshot as build_formula_decision_from_snapshot,
    formula_parameters_for_user,
    maybe_create_formula_suggestion,
    target_kwargs_for_side,
)
from app.services.crew_models import (
    _sanitize_llm_json,
    complete_model_invocation,
    effective_model,
    invoke_ollama_json,
    mark_invocation_validation_failed,
)
from app.services.crew_portfolio import (
    get_or_create_ai_account,
    latest_price,
    maybe_reset_bankroll,
    record_portfolio_snapshot,
    recent_lessons_for_prompt,
)
from app.services.crew_runner import (
    AGENT_ROLES,
    AgentDecision,
    PredictionPoint,
    _build_snapshot,
    _run_backtest_for_recommendation,
    _select_ready_assets,
    _store_prediction,
    _store_recommendation,
    runtime_status,
)
from app.services.crew_trace import trace_event, trace_event_once_per_window, utc_isoformat
from app.services.market_candles import load_candles_df
from app.services.market_resolution import configured_exchange_priority
from app.trading.formulas import add_formula_indicators, formula_targets


FORMULA_ENTRY_SCORE_FLOOR = 0.50
FORMULA_FULL_SIZE_SCORE = 0.60
AGGRESSIVE_RESEARCH_SYMBOL_LIMIT = 3
AGGRESSIVE_THESIS_TIMEOUT_SECONDS = 120
AGGRESSIVE_TRADE_NOTE_TIMEOUT_SECONDS = 45


class ThesisDecision(BaseModel):
    action: Literal["buy", "short", "hold", "reject"] = "hold"
    confidence: float = Field(ge=0, le=1)
    thesis: str = Field(min_length=5, max_length=4000)
    risk_notes: str | None = Field(default=None, max_length=4000)
    strategy_name: str = "formula_long_momentum"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    side: Literal["long", "short"] = "long"
    sleeve: Literal["long", "short"] = "long"
    entry_score: float | None = Field(default=None, ge=0, le=1)
    exit_score: float | None = Field(default=None, ge=0, le=1)
    formula_inputs: dict[str, Any] = Field(default_factory=dict)
    formula_outputs: dict[str, Any] = Field(default_factory=dict)
    strategy_version: str = "formula-v1"
    # "immediate" = execute now (fair value model); legacy "at_or_below"/"at_or_above" still accepted
    entry_condition: Literal["immediate", "at_or_below", "at_or_above"] = "immediate"
    fair_value: float | None = Field(default=None, gt=0)
    entry_target: float | None = Field(default=None, gt=0)
    take_profit_target: float | None = Field(default=None, gt=0)
    stop_loss_target: float | None = Field(default=None, gt=0)
    expires_in_minutes: int = Field(default=240, ge=15, le=10080)
    prediction_summary: str | None = Field(default=None, max_length=4000)
    prediction_horizon_minutes: int = Field(default=240, ge=15, le=10080)
    predicted_path: list[PredictionPoint] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def clean_rejection_path(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("action") == "reject":
                if "predicted_path" in data:
                    data["predicted_path"] = []
            # Normalise legacy entry_condition values to "immediate"
            ec = data.get("entry_condition", "")
            if isinstance(ec, str) and ec.strip().lower() in ("at_or_below", "at_or_above", "market", "now"):
                data["entry_condition"] = "immediate"
            action = str(data.get("action") or "").strip().lower()
            if action == "short":
                data["side"] = "short"
                data["sleeve"] = "short"
                data.setdefault("strategy_name", "formula_quick_short")
            elif action == "buy":
                data["side"] = "long"
                data["sleeve"] = "long"
                data.setdefault("strategy_name", "formula_long_momentum")
        return data




class TradeApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=5, max_length=4000)
    risk_notes: str | None = Field(default=None, max_length=4000)


class OllamaThesisClient:
    last_prompt: str | None = None
    last_raw_response: str | None = None
    last_parsed_response: dict[str, Any] | None = None

    def __init__(
        self,
        *,
        model: str | None = None,
        db: Session | None = None,
        current_user: User | None = None,
        run: AgentRun | None = None,
    ):
        self.model = model or settings.CREW_LLM_MODEL
        self.db = db
        self.current_user = current_user
        self.run = run

    def generate_thesis(
        self,
        snapshot: dict[str, Any],
        lessons: list[dict[str, Any]],
        *,
        trade_cadence_mode: str = "standard",
        snapshot_id: int | None = None,
        exchange: str | None = None,
        symbol: str | None = None,
    ) -> ThesisDecision:
        if trade_cadence_mode == "aggressive_paper":
            decision = build_formula_decision_from_snapshot(
                snapshot,
                snapshot.get("latest_price"),
                snapshot,
                reason="Deterministic Fast-Lane bypass."
            )
            if decision and decision.entry_score and decision.entry_score >= FORMULA_ENTRY_SCORE_FLOOR:
                self.last_parsed_response = decision.model_dump()
                self.last_raw_response = json.dumps(self.last_parsed_response)
                self.last_prompt = "Deterministic Fast-Lane bypass."
                return decision

        prompt = _build_thesis_prompt(snapshot, lessons, trade_cadence_mode=trade_cadence_mode)
        timeout_seconds = _llm_timeout_for("thesis", trade_cadence_mode)
        def _invoke(current_prompt: str):
            self.last_parsed_response = None
            if self.db is not None and self.current_user is not None:
                parsed, raw, invocation = invoke_ollama_json(
                    self.db,
                    self.current_user,
                    role="thesis",
                    action_type="research_thesis",
                    model=self.model,
                    prompt=current_prompt,
                    run_id=self.run.id if self.run else None,
                    snapshot_id=snapshot_id,
                    exchange=exchange,
                    symbol=symbol,
                    timeout_seconds=timeout_seconds,
                )
            else:
                _read_timeout = timeout_seconds
                response = requests.post(
                    f"{settings.CREW_LLM_BASE_URL.rstrip('/')}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": current_prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1},
                    },
                    timeout=(min(30, _read_timeout), _read_timeout),
                )
                response.raise_for_status()
                raw = response.json().get("response")
                if not raw or not raw.strip():
                    raise ValueError("Ollama returned an empty thesis response.")
                sanitized = _sanitize_llm_json(raw)
                try:
                    parsed = json.loads(sanitized)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Agent thesis response was not valid JSON after sanitization: {exc}") from exc
                invocation = None
            self.last_parsed_response = parsed
            self.last_raw_response = raw
            return parsed, raw, invocation

        try:
            parsed, raw, invocation = _invoke(prompt)
            return ThesisDecision.model_validate(parsed)
        except ValidationError as exc:
            if invocation is not None and self.db is not None:
                mark_invocation_validation_failed(self.db, invocation, str(exc))
            
            retry_prompt = prompt + f"\n\nYOUR PREVIOUS ATTEMPT FAILED WITH VALIDATION ERROR:\n{exc}\n\nREWRITE AND OUTPUT ONLY VALID JSON WITHOUT INLINE COMMENTS."
            try:
                parsed, raw, invocation = _invoke(retry_prompt)
                return ThesisDecision.model_validate(parsed)
            except ValidationError as exc2:
                if invocation is not None and self.db is not None:
                    mark_invocation_validation_failed(self.db, invocation, str(exc2))
                raise ValueError(f"Agent thesis failed schema validation after retry: {exc2}") from exc2


class OllamaTradeDecisionClient:
    last_prompt: str | None = None
    last_raw_response: str | None = None
    last_parsed_response: dict[str, Any] | None = None

    def __init__(self, *, model: str, db: Session, current_user: User):
        self.model = model
        self.db = db
        self.current_user = current_user

    def review_trade(
        self,
        *,
        thesis: AgentResearchThesis,
        recommendation: AgentRecommendation,
        action: str,
        price: float,
    ) -> tuple[TradeApprovalDecision, Any]:
        prompt = _build_trade_decision_prompt(thesis, recommendation, action, price)
        timeout_seconds = _llm_timeout_for(
            "trade",
            getattr(get_or_create_guardrails(self.db, self.current_user), "trade_cadence_mode", None) or "standard",
        )
        self.last_prompt = prompt
        parsed, raw, invocation = invoke_ollama_json(
            self.db,
            self.current_user,
            role="trade",
            action_type="trade_decision",
            model=self.model,
            prompt=prompt,
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            timeout_seconds=timeout_seconds,
        )
        self.last_raw_response = raw
        self.last_parsed_response = parsed
        try:
            decision = TradeApprovalDecision.model_validate(parsed)
        except ValidationError as exc:
            mark_invocation_validation_failed(self.db, invocation, str(exc))
            raise ValueError(f"Trade decision failed schema validation: {exc}") from exc
        return decision, invocation


def run_autonomous_research_cycle(
    db: Session,
    current_user: User,
    *,
    max_symbols: int | None = None,
    execute_immediate: bool = True,
    run_id: int | None = None,
) -> dict[str, Any]:
    profile = get_or_create_guardrails(db, current_user)
    thesis_model = FORMULA_ENGINE_MODEL
    formula_params = formula_parameters_for_user(db, current_user)
    trade_cadence = profile.trade_cadence_mode or "aggressive_paper"
    if not settings.CREW_RESEARCH_ENABLED or not profile.research_enabled:
        trace_event(
            db,
            current_user,
            event_type="research_blocked",
            status="blocked",
            public_summary="Autonomous research skipped because research is disabled.",
            role="Market Data Auditor",
            blocker_reason="CREW_RESEARCH_ENABLED is false or this user's research flag is disabled.",
        )
        return {"status": "disabled", "reason": "Autonomous research is disabled."}

    status = runtime_status()

    account = get_or_create_ai_account(db, current_user)
    default_max = AGGRESSIVE_RESEARCH_SYMBOL_LIMIT if trade_cadence == "aggressive_paper" else settings.CREW_MAX_SYMBOLS_PER_RUN
    max_count = max(1, min(max_symbols or default_max, settings.CREW_MAX_SYMBOLS_PER_RUN))
    run = None
    if run_id is not None:
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.user_id == current_user.id)
            .first()
        )
    if run is None:
        run = AgentRun(
            user_id=current_user.id,
            status="running",
            mode="autonomous_research",
            llm_provider="formula",
            llm_base_url=None,
            llm_model=thesis_model,
            max_symbols=max_count,
            requested_symbols=[],
            selected_symbols=[],
            summary={"agents": AGENT_ROLES, "mode": "autonomous_research"},
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
    else:
        run.status = "running"
        run.llm_provider = "formula"
        run.llm_base_url = None
        run.llm_model = thesis_model
        run.max_symbols = max_count
        run.started_at = run.started_at or datetime.now(timezone.utc)
        run.completed_at = None
        run.error_message = None
        run.summary = {
            **(run.summary or {}),
            "agents": AGENT_ROLES,
            "mode": "autonomous_research",
            "progress": "running",
            "execute_immediate": execute_immediate,
        }
    db.flush()
    audit(db, current_user, "autonomous_research_started", {"run_id": run.id, "account_id": account.id})
    trace_event(
        db,
        current_user,
        event_type="research_started",
        status="running",
        public_summary=f"Research cycle started for up to {max_count} ready assets.",
        role="Market Data Auditor",
        run_id=run.id,
        rationale="The scheduler selected this user because autonomous research is enabled.",
        evidence={
            "account_id": account.id,
            "max_symbols": max_count,
            "trade_cadence_mode": trade_cadence,
            "runtime": status,
            "formula_config": {
                "entry_score_floor": formula_params.get("entry_score_floor"),
                "full_size_score": formula_params.get("full_size_score"),
                "version": formula_params.get("version"),
            },
            "reason_code": "research_running",
        },
    )
    _commit_progress(db, run)

    assets = _select_autonomous_assets(db, current_user, max_count)
    if not assets:
        trace_event(
            db,
            current_user,
            event_type="research_blocked",
            status="blocked",
            public_summary="Research found no ready, analyzable assets.",
            role="Market Data Auditor",
            run_id=run.id,
            blocker_reason="No asset met ready/analyzable candle requirements.",
            evidence={"max_symbols": max_count},
        )
        _commit_progress(db, run)
    lessons = recent_lessons_for_prompt(db, current_user)
    created = 0
    rejected = 0
    selected: list[str] = []
    stopped_reason: str | None = None

    for asset in assets:
        snapshot = _build_snapshot(db, current_user, run, asset)
        if snapshot is None:
            continue
        selected.append(snapshot.symbol)
        run.selected_symbols = selected
        run.summary = {
            **(run.summary or {}),
            "selected": selected,
            "current_symbol": snapshot.symbol,
            "progress": "snapshot_built",
            "theses_created": created,
            "rejected": rejected,
        }
        trace_event(
            db,
            current_user,
            event_type="snapshot_built",
            status="completed",
            public_summary=f"{snapshot.symbol} research snapshot built from {snapshot.exchange.upper()} data.",
            role="Market Data Auditor",
            run_id=run.id,
            snapshot_id=snapshot.id,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            evidence={
                "row_count": snapshot.row_count,
                "price": snapshot.price,
                "data_status": snapshot.data_status,
                "signal": snapshot.signal,
                "reason_code": "research_running",
            },
        )
        _commit_progress(db, run)
        thesis_payload = build_formula_decision_from_snapshot(
            snapshot.snapshot,
            snapshot.price,
            snapshot.signal,
            parameters=formula_params,
            reason="Autonomous research used the deterministic formula engine.",
        )
        if thesis_payload is None:
            rejected += 1
            reason = "No formula sleeve met the configured entry score floor."
            audit(
                db,
                current_user,
                "formula_thesis_rejected",
                {"run_id": run.id, "snapshot_id": snapshot.id, "symbol": snapshot.symbol, "reason": reason},
            )
            trace_event(
                db,
                current_user,
                event_type="thesis_rejected",
                status="blocked",
                public_summary=f"{snapshot.symbol} did not meet the deterministic formula entry floor.",
                role="Portfolio Manager",
                run_id=run.id,
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
                blocker_reason=reason,
                evidence={
                    "reason_code": "formula_entry_floor",
                    "entry_score_floor": formula_params.get("entry_score_floor"),
                    "formula_metrics": (snapshot.signal or {}).get("formula_metrics") if isinstance(snapshot.signal, dict) else None,
                },
                model_role="formula",
                llm_model=None,
            )
            _commit_progress(db, run)
            continue
        thesis_decision = ThesisDecision.model_validate(thesis_payload)

        decision = _to_agent_decision(thesis_decision)
        prediction = _store_prediction(db, current_user, run, snapshot, decision)
        recommendation = _store_recommendation(
            db=db,
            current_user=current_user,
            run=run,
            snapshot=snapshot,
            prediction=prediction,
            decision=decision,
            paper_account_id=account.id,
            model_role="formula",
            llm_model=None,
        )
        run.summary = {
            **(run.summary or {}),
            "selected": selected,
            "current_symbol": snapshot.symbol,
            "progress": "backtesting",
            "theses_created": created,
            "rejected": rejected,
        }
        _commit_progress(db, run, recommendation)
        backtest_run, backtest_summary = _run_backtest_for_recommendation(db, current_user, recommendation, decision)
        if backtest_run is not None:
            recommendation.backtest_run_id = backtest_run.id
            recommendation.backtest_summary = backtest_summary
            recommendation.status = "proposed"
            recommendation.execution_reason = "Backtest completed; standing trigger thesis created."
            trace_event(
                db,
                current_user,
                event_type="backtest_passed",
                status="completed",
                public_summary=f"{snapshot.symbol} backtest completed; thesis can be monitored for triggers.",
                role="Backtest Analyst",
                run_id=run.id,
                recommendation_id=recommendation.id,
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
                evidence={**backtest_summary, "reason_code": "backtest_completed"},
            )
            _commit_progress(db, run, recommendation, backtest_run)
        else:
            recommendation.status = "rejected"
            recommendation.backtest_summary = backtest_summary
            recommendation.execution_reason = backtest_summary.get("reason", "Backtest did not complete.")
            recommendation.execution_decision = recommendation.execution_reason
            trace_event(
                db,
                current_user,
                event_type="backtest_failed",
                status="blocked",
                public_summary=f"{snapshot.symbol} thesis failed required backtest proof.",
                role="Backtest Analyst",
                run_id=run.id,
                recommendation_id=recommendation.id,
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
                blocker_reason=recommendation.execution_reason,
                evidence={**backtest_summary, "reason_code": "backtest_failed"},
            )
            rejected += 1
            run.summary = {
                **(run.summary or {}),
                "selected": selected,
                "current_symbol": snapshot.symbol,
                "progress": "backtest_failed",
                "theses_created": created,
                "rejected": rejected,
                "latest_blocker": recommendation.execution_reason,
            }
            _commit_progress(db, run, recommendation)
            continue

        thesis = _store_thesis(
            db=db,
            current_user=current_user,
            account_id=account.id,
            run_id=run.id,
            snapshot_id=snapshot.id,
            recommendation_id=recommendation.id,
            decision=thesis_decision,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            price=snapshot.price,
            lessons=lessons,
            model_role="formula",
            llm_model=None,
        )
        created += 1
        audit(
            db,
            current_user,
            "research_thesis_created",
            {
                "run_id": run.id,
                "thesis_id": thesis.id,
                "symbol": thesis.symbol,
                "entry_target": thesis.entry_target,
                "take_profit_target": thesis.take_profit_target,
                "stop_loss_target": thesis.stop_loss_target,
            },
            recommendation.id,
        )
        trace_event(
            db,
            current_user,
            event_type="thesis_created",
            status="waiting",
            public_summary=f"{thesis.symbol} active thesis created; waiting for entry target.",
            role="Portfolio Manager",
            run_id=run.id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=snapshot.id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            rationale=thesis.thesis,
            evidence={
                "confidence": thesis.confidence,
                "entry_condition": thesis.entry_condition,
                "entry_target": thesis.entry_target,
                "take_profit_target": thesis.take_profit_target,
                "stop_loss_target": thesis.stop_loss_target,
                "expires_at": thesis.expires_at.isoformat() if thesis.expires_at else None,
                "backtest_status": backtest_summary.get("status"),
                "formula_config": {
                    "entry_score_floor": formula_params.get("entry_score_floor"),
                    "full_size_score": formula_params.get("full_size_score"),
                    "version": formula_params.get("version"),
                },
                "model_role": "formula",
            },
            model_role="formula",
            llm_model=None,
        )
        run.summary = {
            **(run.summary or {}),
            "selected": selected,
            "current_symbol": snapshot.symbol,
            "progress": "thesis_created",
            "theses_created": created,
            "rejected": rejected,
            "latest_thesis_id": thesis.id,
        }
        _commit_progress(db, run, thesis, recommendation)
        if execute_immediate and thesis.entry_condition == "immediate":
            price, price_ts = latest_price(db, thesis.exchange, thesis.symbol)
            entry_price = float(price or thesis.entry_target or snapshot.price or 0.0)
            if entry_price > 0:
                immediate_result = _execute_thesis_entry(
                    db,
                    current_user,
                    account=account,
                    profile=profile,
                    thesis=thesis,
                    price=entry_price,
                    price_ts=price_ts or snapshot.source_data_timestamp,
                    now=datetime.now(timezone.utc),
                    formula_first=True,
                )
                if immediate_result.get("status") == "ok":
                    run.summary = {
                        **(run.summary or {}),
                        "progress": "paper_order_executed",
                        "latest_execution": immediate_result,
                    }
                    _commit_progress(db, run, thesis)
                    break
                run.summary = {
                    **(run.summary or {}),
                    "progress": "paper_order_not_executed",
                    "latest_execution": immediate_result,
                }
                _commit_progress(db, run, thesis)

    run.status = "completed"
    run.selected_symbols = selected
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {
        **(run.summary or {}),
        "runtime": status,
        "agents": AGENT_ROLES,
        "selected": selected,
        "theses_created": created,
        "rejected": rejected,
        "stopped_reason": stopped_reason,
        "formula_config": {
            "entry_score_floor": formula_params.get("entry_score_floor"),
            "full_size_score": formula_params.get("full_size_score"),
            "version": formula_params.get("version"),
        },
        "llm_model": None,
        "execute_immediate": execute_immediate,
        "progress": "completed",
    }
    record_portfolio_snapshot(db, current_user, account)
    audit(db, current_user, "autonomous_research_completed", {"run_id": run.id, "summary": run.summary})
    trace_event(
        db,
        current_user,
        event_type="research_completed",
        status="completed",
        public_summary=(
            f"Research cycle stopped early with {created} active theses and {rejected} rejected ideas."
            if stopped_reason
            else f"Research cycle completed with {created} active theses and {rejected} rejected ideas."
        ),
        role="Market Data Auditor",
        run_id=run.id,
        blocker_reason=stopped_reason,
        evidence={**run.summary, "reason_code": "research_completed"},
    )
    db.commit()
    return {
        "status": "completed",
        "run_id": run.id,
        "theses_created": created,
        "rejected": rejected,
        "stopped_reason": stopped_reason,
    }


def dry_run_research_thesis(
    db: Session,
    current_user: User,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    thesis_model = FORMULA_ENGINE_MODEL
    formula_params = formula_parameters_for_user(db, current_user)
    run = AgentRun(
        user_id=current_user.id,
        status="running",
        mode="research_dry_run",
        llm_provider="formula",
        llm_base_url=None,
        llm_model=thesis_model,
        max_symbols=1,
        requested_symbols=[symbol] if symbol else [],
        selected_symbols=[],
        summary={
            "mode": "research_dry_run",
            "formula_config": {
                "entry_score_floor": formula_params.get("entry_score_floor"),
                "full_size_score": formula_params.get("full_size_score"),
                "version": formula_params.get("version"),
            },
        },
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()

    assets = _select_autonomous_assets(db, current_user, 25)
    if symbol:
        wanted = symbol.strip().upper().replace("/", "-")
        assets = [asset for asset in assets if (asset.symbol or "").upper() == wanted]
    asset = assets[0] if assets else None
    if asset is None:
        run.status = "failed"
        run.error_message = "No ready, analyzable asset was available for a thesis dry-run."
        run.completed_at = datetime.now(timezone.utc)
        trace_event(
            db,
            current_user,
            event_type="research_dry_run_blocked",
            status="blocked",
            public_summary="Research dry-run found no ready, analyzable asset.",
            role="Market Data Auditor",
            run_id=run.id,
            blocker_reason=run.error_message,
            evidence={"requested_symbol": symbol},
            model_role="formula",
            llm_model=None,
        )
        db.commit()
        return {
            "ok": False,
            "status": "no_ready_asset",
            "run_id": run.id,
            "model": thesis_model,
            "message": run.error_message,
        }

    snapshot = _build_snapshot(db, current_user, run, asset)
    if snapshot is None:
        run.status = "failed"
        run.error_message = "Unable to build a research snapshot for the selected asset."
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "ok": False,
            "status": "snapshot_failed",
            "run_id": run.id,
            "model": thesis_model,
            "message": run.error_message,
        }

    run.selected_symbols = [snapshot.symbol]
    trace_event(
        db,
        current_user,
        event_type="research_dry_run_started",
        status="running",
        public_summary=f"Testing deterministic formula engine against one {snapshot.exchange.upper()} thesis snapshot.",
        role="Market Data Auditor",
        run_id=run.id,
        snapshot_id=snapshot.id,
        exchange=snapshot.exchange,
        symbol=snapshot.symbol,
        evidence={
            "row_count": snapshot.row_count,
            "price": snapshot.price,
            "entry_score_floor": formula_params.get("entry_score_floor"),
        },
        model_role="formula",
        llm_model=None,
    )

    decision_payload = build_formula_decision_from_snapshot(
        snapshot.snapshot,
        snapshot.price,
        snapshot.signal,
        parameters=formula_params,
        reason="Research dry-run used the deterministic formula engine.",
    )
    if decision_payload is None:
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        run.summary = {
            "mode": "research_dry_run",
            "symbol": snapshot.symbol,
            "exchange": snapshot.exchange,
            "model": thesis_model,
            "decision": None,
            "reason": "No formula sleeve met the configured entry score floor.",
            "formula_config": {
                "entry_score_floor": formula_params.get("entry_score_floor"),
                "full_size_score": formula_params.get("full_size_score"),
                "version": formula_params.get("version"),
            },
        }
        trace_event(
            db,
            current_user,
            event_type="research_dry_run_completed",
            status="rejected",
            public_summary=f"Formula dry-run rejected {snapshot.symbol}; no sleeve cleared the entry threshold.",
            role="Thesis Strategist",
            run_id=run.id,
            snapshot_id=snapshot.id,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            blocker_reason="No formula sleeve met the configured entry score floor.",
            evidence=run.summary,
            model_role="formula",
            llm_model=None,
        )
        db.commit()
        return {
            "ok": False,
            "status": "formula_rejected",
            "run_id": run.id,
            "model": thesis_model,
            "symbol": snapshot.symbol,
            "exchange": snapshot.exchange,
            "message": "No formula sleeve met the configured entry score floor.",
        }

    decision = ThesisDecision.model_validate(decision_payload)
    payload = decision.model_dump(mode="json")
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {
        "mode": "research_dry_run",
        "symbol": snapshot.symbol,
        "exchange": snapshot.exchange,
        "model": thesis_model,
        "decision": payload,
        "formula_config": {
            "entry_score_floor": formula_params.get("entry_score_floor"),
            "full_size_score": formula_params.get("full_size_score"),
            "version": formula_params.get("version"),
        },
    }
    trace_event(
        db,
        current_user,
        event_type="research_dry_run_completed",
        status="completed",
        public_summary=f"Formula engine produced a valid {snapshot.symbol} thesis dry-run.",
        role="Thesis Strategist",
        run_id=run.id,
        snapshot_id=snapshot.id,
        exchange=snapshot.exchange,
        symbol=snapshot.symbol,
        rationale=decision.thesis,
        evidence=payload,
        model_role="formula",
        llm_model=None,
    )
    db.commit()
    return {
        "ok": True,
        "status": "ok",
        "run_id": run.id,
        "model": thesis_model,
        "symbol": snapshot.symbol,
        "exchange": snapshot.exchange,
        "message": "Formula engine produced a valid thesis payload.",
        "decision": payload,
    }


def monitor_price_triggers(db: Session, current_user: User) -> dict[str, Any]:
    profile = get_or_create_guardrails(db, current_user)
    if not settings.CREW_TRIGGER_MONITOR_ENABLED or not profile.trigger_monitor_enabled:
        trace_event(
            db,
            current_user,
            event_type="trigger_monitor_blocked",
            status="blocked",
            public_summary="Trigger monitor skipped because monitoring is disabled.",
            role="Trigger Monitor",
            blocker_reason="CREW_TRIGGER_MONITOR_ENABLED is false or this user's monitor flag is disabled.",
        )
        return {"status": "disabled", "reason": "Trigger monitor is disabled."}
    if not profile.autonomous_enabled:
        trace_event(
            db,
            current_user,
            event_type="trigger_monitor_blocked",
            status="paused",
            public_summary="Trigger monitor skipped because autonomous paper trading is paused.",
            role="Trigger Monitor",
            blocker_reason="autonomous_enabled is false.",
        )
        return {"status": "paused", "reason": "Autonomous paper trading is paused."}

    account = get_or_create_ai_account(db, current_user)
    now = datetime.now(timezone.utc)
    open_positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account.id, PaperPosition.quantity > 0)
        .order_by(PaperPosition.symbol.asc(), PaperPosition.side.asc())
        .all()
    )
    theses = (
        db.query(AgentResearchThesis)
        .filter(
            AgentResearchThesis.user_id == current_user.id,
            AgentResearchThesis.account_id == account.id,
            AgentResearchThesis.status.in_(("active", "entry_triggered")),
        )
        .order_by(AgentResearchThesis.created_at.asc())
        .all()
    )
    results = {
        "status": "ok",
        "checked": len(theses),
        "positions_checked": len(open_positions),
        "executed": 0,
        "blocked": 0,
        "expired": 0,
        "missed": 0,
        "repaired": 0,
        "unmanaged": 0,
    }
    if not theses and not open_positions:
        trace_event_once_per_window(
            db,
            current_user,
            window_seconds=300,
            event_type="trigger_waiting",
            status="waiting",
            public_summary="Trigger monitor is running but no active theses or open positions are available.",
            role="Trigger Monitor",
            blocker_reason="No active or entry-triggered thesis records and no open AI paper positions.",
        )

    for thesis in theses:
        expires_at = _as_aware(thesis.expires_at)
        if expires_at and expires_at <= now and thesis.status == "active":
            thesis.status = "expired"
            thesis.closed_at = now
            results["expired"] += 1
            _write_lesson(
                db,
                current_user,
                account.id,
                thesis,
                outcome="expired",
                return_pct=None,
                lesson=f"{thesis.symbol} thesis expired before trigger; future plans should use tighter targets or shorter monitoring windows.",
            )
            audit(db, current_user, "trigger_expired", {"thesis_id": thesis.id, "symbol": thesis.symbol}, thesis.recommendation_id)
            trace_event(
                db,
                current_user,
                event_type="trigger_expired",
                status="expired",
                public_summary=f"{thesis.symbol} thesis expired before execution.",
                role="Trigger Monitor",
                run_id=thesis.run_id,
                recommendation_id=thesis.recommendation_id,
                thesis_id=thesis.id,
                snapshot_id=thesis.snapshot_id,
                exchange=thesis.exchange,
                symbol=thesis.symbol,
                blocker_reason="The thesis expiry time passed before trigger conditions were met.",
            )
            continue

        price, price_ts = latest_price(db, thesis.exchange, thesis.symbol)
        if price is None:
            results["missed"] += 1
            trace_event(
                db,
                current_user,
                event_type="trigger_waiting",
                status="waiting",
                public_summary=f"{thesis.symbol} trigger waiting for a fresh market price.",
                role="Trigger Monitor",
                run_id=thesis.run_id,
                recommendation_id=thesis.recommendation_id,
                thesis_id=thesis.id,
                snapshot_id=thesis.snapshot_id,
                exchange=thesis.exchange,
                symbol=thesis.symbol,
                blocker_reason="No latest candle price is available.",
            )
            continue
        thesis.latest_observed_price = price

        position = _position_for_thesis(db, account.id, thesis)
        if thesis.status == "active" and position is None:
            if not _entry_crossed(thesis, price):
                results["missed"] += 1
                trace_event(
                    db,
                    current_user,
                    event_type="trigger_waiting",
                    status="waiting",
                    public_summary=f"{thesis.symbol} is waiting for entry conditions.",
                    role="Trigger Monitor",
                    run_id=thesis.run_id,
                    recommendation_id=thesis.recommendation_id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    blocker_reason="Entry price condition has not crossed yet.",
                    evidence={
                        "latest_price": price,
                        "entry_condition": thesis.entry_condition,
                        "entry_target": thesis.entry_target,
                        "take_profit_target": thesis.take_profit_target,
                        "stop_loss_target": thesis.stop_loss_target,
                    },
                )
                continue
            entry_action = "short" if thesis.side == "short" else "buy"
            recommendation = _trigger_recommendation(db, current_user, thesis, entry_action, price, account.id, price_ts)
            allowed, reason = check_guardrails(db, current_user, profile, recommendation)
            if not allowed:
                recommendation.status = "rejected"
                recommendation.execution_reason = reason
                recommendation.execution_decision = reason
                results["blocked"] += 1
                _write_lesson(
                    db,
                    current_user,
                    account.id,
                    thesis,
                    outcome="rejected_trigger",
                    return_pct=None,
                    lesson=f"{thesis.symbol} entry trigger was blocked: {reason}",
                    recommendation_id=recommendation.id,
                )
                audit(db, current_user, "entry_trigger_blocked", {"thesis_id": thesis.id, "reason": reason}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="guardrail_blocked",
                    status="blocked",
                    public_summary=f"{thesis.symbol} entry trigger crossed but was blocked.",
                    role="Risk Manager",
                    run_id=thesis.run_id,
                    recommendation_id=recommendation.id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    blocker_reason=reason,
                    evidence={
                        "reason_code": _guardrail_reason_code(reason),
                        "latest_price": price,
                        "entry_target": thesis.entry_target,
                    },
                )
                continue

            recommendation.trade_decision_model = FORMULA_ENGINE_MODEL
            recommendation.trade_decision_status = "formula_approved"
            recommendation.execution_decision = "Deterministic formula trigger crossed and guardrails passed."

            outcome = execute_price_trigger_order(
                db,
                account=account,
                side=entry_action,
                symbol=thesis.symbol,
                exchange=thesis.exchange,
                price=price,
                strategy=thesis.strategy_name,
                reason=f"entry_trigger:{thesis.id}",
                max_position_pct=_entry_position_pct(profile, recommendation),
                take_profit=thesis.take_profit_target,
                stop_loss=thesis.stop_loss_target,
            )
            if outcome.get("status") == "ok":
                thesis.status = "entry_triggered"
                thesis.triggered_at = now
                recommendation.status = "executed"
                recommendation.execution_reason = "Entry target crossed and guardrails passed."
                recommendation.execution_decision = recommendation.execution_reason
                results["executed"] += 1
                entry_lesson_outcome = "paper_short" if entry_action == "short" else "paper_buy"
                _write_lesson(
                    db,
                    current_user,
                    account.id,
                    thesis,
                    outcome=entry_lesson_outcome,
                    return_pct=None,
                    lesson=(
                        f"{thesis.symbol} {entry_action} entry executed at {price:.8g}; "
                        "monitor take-profit, trailing lock, and stop-loss discipline."
                    ),
                    recommendation_id=recommendation.id,
                )
                audit(db, current_user, "entry_trigger_executed", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="paper_order_executed",
                    status="executed",
                    public_summary=f"{thesis.symbol} paper {entry_action} executed after entry trigger crossed.",
                    role="Portfolio Manager",
                    run_id=thesis.run_id,
                    recommendation_id=recommendation.id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    rationale=recommendation.execution_reason,
                    evidence={
                        "result": outcome,
                        "latest_price": price,
                        "entry_target": thesis.entry_target,
                        "side": thesis.side,
                        "sleeve": getattr(thesis, "sleeve", None),
                    },
                )
            else:
                recommendation.status = "rejected"
                recommendation.execution_reason = outcome.get("reason", "Entry trigger could not execute.")
                recommendation.execution_decision = recommendation.execution_reason
                results["blocked"] += 1
                audit(db, current_user, "entry_trigger_rejected", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="paper_order_rejected",
                    status="blocked",
                    public_summary=f"{thesis.symbol} paper {entry_action} trigger could not execute.",
                    role="Portfolio Manager",
                    run_id=thesis.run_id,
                    recommendation_id=recommendation.id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    blocker_reason=recommendation.execution_reason,
                    evidence={"result": outcome},
                )
            continue

        if position is not None:
            continue

    _monitor_position_exits(db, current_user, account, profile, now, results)
    record_portfolio_snapshot(db, current_user, account)
    reset = maybe_reset_bankroll(db, current_user)
    if reset is not None:
        results["reset_id"] = reset.id
        trace_event(
            db,
            current_user,
            event_type="bankroll_reset",
            status="completed",
            public_summary=f"AI bankroll reset #{reset.reset_number} after drawdown guardrail breach.",
            role="Risk Manager",
            blocker_reason=reset.reason,
            evidence={
                "reset_id": reset.id,
                "drawdown_pct": reset.drawdown_pct,
                "equity_before_reset": reset.equity_before_reset,
                "starting_bankroll": reset.starting_bankroll,
            },
        )
    db.commit()
    return results


def theses_payload(db: Session, current_user: User, limit: int = 200) -> list[dict[str, Any]]:
    rows = (
        db.query(AgentResearchThesis)
        .filter(AgentResearchThesis.user_id == current_user.id)
        .order_by(AgentResearchThesis.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_thesis_payload(row) for row in rows]


def update_thesis(
    db: Session,
    current_user: User,
    thesis_id: int,
    changes: dict[str, Any],
) -> AgentResearchThesis | None:
    thesis = (
        db.query(AgentResearchThesis)
        .filter(AgentResearchThesis.id == thesis_id, AgentResearchThesis.user_id == current_user.id)
        .first()
    )
    if thesis is None:
        return None
    for key in (
        "status",
        "entry_target",
        "take_profit_target",
        "stop_loss_target",
        "expires_at",
        "confidence",
        "thesis",
        "risk_notes",
    ):
        if key in changes:
            setattr(thesis, key, changes[key])
    audit(db, current_user, "research_thesis_updated", {"thesis_id": thesis.id, "changes": changes}, thesis.recommendation_id)
    db.commit()
    db.refresh(thesis)
    return thesis


def _select_autonomous_assets(db: Session, current_user: User, max_symbols: int) -> list[AssetDataStatus]:
    owned_symbols = {
        row.symbol
        for row in (
            db.query(PaperPosition)
            .join(AgentResearchThesis, AgentResearchThesis.account_id == PaperPosition.account_id, isouter=True)
            .filter(AgentResearchThesis.user_id == current_user.id)
            .all()
        )
    }
    assets = _select_ready_assets(db, [], max_symbols)
    if owned_symbols:
        owned_assets = (
            db.query(AssetDataStatus)
            .filter(
                AssetDataStatus.status == "ready",
                AssetDataStatus.is_analyzable.is_(True),
                AssetDataStatus.row_count >= 50,
                AssetDataStatus.symbol.in_(owned_symbols),
            )
            .all()
        )
        by_key = {(asset.exchange, asset.symbol): asset for asset in assets}
        for asset in owned_assets:
            by_key[(asset.exchange, asset.symbol)] = asset
        priority = configured_exchange_priority()
        rank = {exchange: idx for idx, exchange in enumerate(priority)}
        sorted_assets = sorted(
            by_key.values(),
            key=lambda asset: (
                rank.get((asset.exchange or "").strip().lower(), 9999),
                -int(asset.row_count or 0),
                asset.symbol,
            ),
        )
        assets = []
        seen_symbols: set[str] = set()
        for asset in sorted_assets:
            symbol_key = (asset.symbol or "").strip().upper()
            if symbol_key in seen_symbols:
                continue
            seen_symbols.add(symbol_key)
            assets.append(asset)
            if len(assets) >= max_symbols:
                break
    return assets


def _store_thesis(
    *,
    db: Session,
    current_user: User,
    account_id: int,
    run_id: int,
    snapshot_id: int,
    recommendation_id: int,
    decision: ThesisDecision,
    exchange: str,
    symbol: str,
    price: float | None,
    lessons: list[dict[str, Any]],
    model_role: str | None = None,
    llm_model: str | None = None,
) -> AgentResearchThesis:
    now = datetime.now(timezone.utc)
    current_price = float(price or decision.entry_target or 1.0)
    side = "short" if decision.action == "short" or decision.side == "short" else "long"
    entry_target = decision.entry_target or current_price
    if side == "short":
        take_profit = decision.take_profit_target or current_price * 0.992
        stop_loss = decision.stop_loss_target or current_price * 1.015
    else:
        take_profit = decision.take_profit_target or current_price * 1.02
        stop_loss = decision.stop_loss_target or current_price * 0.98

    (
        db.query(AgentResearchThesis)
        .filter(
            AgentResearchThesis.user_id == current_user.id,
            AgentResearchThesis.account_id == account_id,
            AgentResearchThesis.exchange == exchange,
            AgentResearchThesis.symbol == symbol,
            AgentResearchThesis.status == "active",
        )
        .update({"status": "superseded", "closed_at": now}, synchronize_session=False)
    )
    thesis = AgentResearchThesis(
        user_id=current_user.id,
        account_id=account_id,
        run_id=run_id,
        snapshot_id=snapshot_id,
        recommendation_id=recommendation_id,
        exchange=exchange,
        symbol=symbol,
        strategy_name=decision.strategy_name.strip().lower(),
        strategy_params=decision.strategy_params or {},
        side=side,
        sleeve=decision.sleeve or side,
        confidence=decision.confidence,
        thesis=decision.thesis,
        risk_notes=decision.risk_notes,
        entry_condition=decision.entry_condition,
        entry_target=entry_target,
        take_profit_target=take_profit,
        stop_loss_target=stop_loss,
        latest_observed_price=current_price,
        status="active",
        expires_at=now + timedelta(minutes=decision.expires_in_minutes),
        lessons_used=lessons,
        metadata_json={
            "prediction_summary": decision.prediction_summary,
            "prediction_horizon_minutes": decision.prediction_horizon_minutes,
            "llm_model": llm_model,
            "model_role": model_role,
        },
        model_role=model_role,
        llm_model=llm_model,
        entry_score=decision.entry_score,
        exit_score=decision.exit_score,
        formula_inputs=decision.formula_inputs or {},
        formula_outputs=decision.formula_outputs or {},
        strategy_version=decision.strategy_version,
    )
    db.add(thesis)
    db.flush()
    return thesis


def _review_trigger_trade(
    db: Session,
    current_user: User,
    profile,
    thesis: AgentResearchThesis,
    recommendation: AgentRecommendation,
    action: str,
    price: float,
):
    trade_model = effective_model(profile, "trade")
    recommendation.model_role = "trade"
    recommendation.llm_model = trade_model
    recommendation.trade_decision_model = trade_model
    client = OllamaTradeDecisionClient(model=trade_model, db=db, current_user=current_user)
    try:
        decision, invocation = client.review_trade(
            thesis=thesis,
            recommendation=recommendation,
            action=action,
            price=price,
        )
    except requests.Timeout as exc:
        reason = f"Trade decision model {trade_model} timed out: {exc}"
        recommendation.trade_decision_status = "timeout"
        audit(db, current_user, "trade_decision_timeout", {"thesis_id": thesis.id, "model": trade_model, "reason": reason}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="trade_decision_failed",
            status="blocked",
            public_summary=f"{thesis.symbol} trigger blocked because the trade decision model timed out.",
            role="Trade Decision",
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            blocker_reason=reason,
            prompt=client.last_prompt,
            model_role="trade",
            llm_model=trade_model,
        )
        return False, reason, trade_model, None
    except Exception as exc:
        reason = f"Trade decision model {trade_model} failed: {exc}"
        recommendation.trade_decision_status = "failed"
        audit(db, current_user, "trade_decision_failed", {"thesis_id": thesis.id, "model": trade_model, "reason": reason}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="trade_decision_failed",
            status="blocked",
            public_summary=f"{thesis.symbol} trigger blocked because the trade decision model failed.",
            role="Trade Decision",
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            blocker_reason=reason,
            prompt=client.last_prompt,
            raw_model_json=client.last_parsed_response,
            validation_error=str(exc),
            model_role="trade",
            llm_model=trade_model,
        )
        return False, reason, trade_model, None

    decision_payload = decision.model_dump(mode="json")
    evidence = dict(recommendation.evidence_json or {})
    evidence["trade_decision"] = decision_payload
    evidence["trade_decision_model"] = trade_model
    recommendation.evidence_json = evidence
    recommendation.trade_decision_status = decision.decision
    recommendation.execution_decision = decision.rationale
    if invocation is not None:
        complete_model_invocation(
            db,
            invocation,
            status="approved" if decision.decision == "approve" else "rejected",
            recommendation_id=recommendation.id,
            response_summary=decision.rationale,
            raw_model_json=decision_payload,
            metadata={"confidence": decision.confidence},
        )
    if decision.decision != "approve":
        reason = decision.rationale
        audit(
            db,
            current_user,
            "trade_decision_rejected",
            {"thesis_id": thesis.id, "model": trade_model, "decision": decision_payload},
            recommendation.id,
        )
        trace_event(
            db,
            current_user,
            event_type="trade_decision_rejected",
            status="blocked",
            public_summary=f"{thesis.symbol} trigger was rejected by the trade decision model.",
            role="Trade Decision",
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            rationale=decision.rationale,
            blocker_reason=reason,
            evidence={"decision": decision_payload, "latest_price": price, "action": action},
            prompt=client.last_prompt,
            raw_model_json=client.last_parsed_response,
            model_role="trade",
            llm_model=trade_model,
        )
        return False, reason, trade_model, invocation

    audit(
        db,
        current_user,
        "trade_decision_approved",
        {"thesis_id": thesis.id, "model": trade_model, "decision": decision_payload},
        recommendation.id,
    )
    trace_event(
        db,
        current_user,
        event_type="trade_decision_approved",
        status="completed",
        public_summary=f"{thesis.symbol} {action} trigger approved by the trade decision model.",
        role="Trade Decision",
        run_id=thesis.run_id,
        recommendation_id=recommendation.id,
        thesis_id=thesis.id,
        snapshot_id=thesis.snapshot_id,
        exchange=thesis.exchange,
        symbol=thesis.symbol,
        rationale=decision.rationale,
        evidence={"decision": decision_payload, "latest_price": price, "action": action},
        prompt=client.last_prompt,
        raw_model_json=client.last_parsed_response,
        model_role="trade",
        llm_model=trade_model,
    )
    return True, decision.rationale, trade_model, invocation


def _trigger_recommendation(
    db: Session,
    current_user: User,
    thesis: AgentResearchThesis,
    action: str,
    price: float,
    account_id: int,
    price_ts: datetime | None,
) -> AgentRecommendation:
    source = None
    if thesis.recommendation_id:
        source = (
            db.query(AgentRecommendation)
            .filter(AgentRecommendation.id == thesis.recommendation_id, AgentRecommendation.user_id == current_user.id)
            .first()
        )
    rec_side = "short" if action in {"short", "cover"} or thesis.side == "short" else "long"
    recommendation = AgentRecommendation(
        user_id=current_user.id,
        agent_name="Trigger Monitor",
        strategy_name=thesis.strategy_name,
        exchange=thesis.exchange,
        symbol=thesis.symbol,
        action=action,
        side=rec_side,
        sleeve=getattr(thesis, "sleeve", None) or rec_side,
        confidence=thesis.confidence,
        thesis=thesis.thesis,
        risk_notes=thesis.risk_notes,
        source_data_timestamp=price_ts,
        expires_at=thesis.expires_at,
        run_id=thesis.run_id,
        snapshot_id=thesis.snapshot_id,
        prediction_id=source.prediction_id if source else None,
        backtest_run_id=source.backtest_run_id if source else None,
        paper_account_id=account_id,
        status="proposed",
        model_role="trade",
        entry_score=getattr(thesis, "entry_score", None),
        exit_score=getattr(thesis, "exit_score", None),
        formula_inputs=getattr(thesis, "formula_inputs", None) or {},
        formula_outputs=getattr(thesis, "formula_outputs", None) or {},
        strategy_version=getattr(thesis, "strategy_version", None),
        evidence_json={
            "thesis_id": thesis.id,
            "trigger_price": price,
            "side": rec_side,
            "sleeve": getattr(thesis, "sleeve", None) or rec_side,
            "entry_score": getattr(thesis, "entry_score", None),
            "exit_score": getattr(thesis, "exit_score", None),
            "formula_inputs": getattr(thesis, "formula_inputs", None) or {},
            "formula_outputs": getattr(thesis, "formula_outputs", None) or {},
            "strategy_version": getattr(thesis, "strategy_version", None),
            "entry_target": thesis.entry_target,
            "take_profit_target": thesis.take_profit_target,
            "stop_loss_target": thesis.stop_loss_target,
            "source_recommendation_id": thesis.recommendation_id,
            "source_thesis_model": thesis.llm_model,
        },
        backtest_summary=source.backtest_summary if source else {},
    )
    db.add(recommendation)
    db.flush()
    return recommendation


def _execute_thesis_entry(
    db: Session,
    current_user: User,
    *,
    account,
    profile,
    thesis: AgentResearchThesis,
    price: float,
    price_ts: datetime | None,
    now: datetime,
    formula_first: bool,
) -> dict[str, Any]:
    if _position_for_thesis(db, account.id, thesis) is not None:
        return {"status": "skipped", "reason": "position_already_open", "thesis_id": thesis.id}

    entry_action = "short" if thesis.side == "short" else "buy"
    recommendation = _trigger_recommendation(db, current_user, thesis, entry_action, price, account.id, price_ts)
    allowed, reason = check_guardrails(db, current_user, profile, recommendation)
    if not allowed:
        recommendation.status = "rejected"
        recommendation.execution_reason = reason
        recommendation.execution_decision = reason
        _write_lesson(
            db,
            current_user,
            account.id,
            thesis,
            outcome="rejected_trigger",
            return_pct=None,
            lesson=f"{thesis.symbol} entry trigger was blocked: {reason}",
            recommendation_id=recommendation.id,
        )
        audit(db, current_user, "entry_trigger_blocked", {"thesis_id": thesis.id, "reason": reason}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="guardrail_blocked",
            status="blocked",
            public_summary=f"{thesis.symbol} formula-first entry crossed but was blocked.",
            role="Risk Manager",
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            blocker_reason=reason,
            evidence={
                "reason_code": _guardrail_reason_code(reason),
                "latest_price": price,
                "entry_target": thesis.entry_target,
            },
        )
        return {"status": "blocked", "reason": reason, "recommendation_id": recommendation.id}

    recommendation.trade_decision_model = FORMULA_ENGINE_MODEL
    recommendation.trade_decision_status = "formula_approved"
    recommendation.execution_decision = "Deterministic formula trigger crossed and guardrails passed."

    outcome = execute_price_trigger_order(
        db,
        account=account,
        side=entry_action,
        symbol=thesis.symbol,
        exchange=thesis.exchange,
        price=price,
        strategy=thesis.strategy_name,
        reason=f"entry_trigger:{thesis.id}",
        max_position_pct=_entry_position_pct(profile, recommendation),
        take_profit=thesis.take_profit_target,
        stop_loss=thesis.stop_loss_target,
    )
    if outcome.get("status") == "ok":
        thesis.status = "entry_triggered"
        thesis.triggered_at = now
        recommendation.status = "executed"
        recommendation.execution_reason = "Formula-first entry crossed and guardrails passed."
        recommendation.execution_decision = recommendation.execution_reason
        entry_lesson_outcome = "paper_short" if entry_action == "short" else "paper_buy"
        _write_lesson(
            db,
            current_user,
            account.id,
            thesis,
            outcome=entry_lesson_outcome,
            return_pct=None,
            lesson=(
                f"{thesis.symbol} {entry_action} entry executed at {price:.8g}; "
                "monitor take-profit, trailing lock, and stop-loss discipline."
            ),
            recommendation_id=recommendation.id,
        )
        audit(db, current_user, "entry_trigger_executed", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="paper_order_executed",
            status="executed",
            public_summary=f"{thesis.symbol} paper {entry_action} executed by formula-first research.",
            role="Portfolio Manager",
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=thesis.exchange,
            symbol=thesis.symbol,
            rationale=recommendation.execution_reason,
            evidence={
                "reason_code": "formula_entry_executed",
                "result": outcome,
                "latest_price": price,
                "entry_target": thesis.entry_target,
                "side": thesis.side,
                "sleeve": getattr(thesis, "sleeve", None),
            },
        )
        record_portfolio_snapshot(db, current_user, account)
        return {"status": "ok", "recommendation_id": recommendation.id, "result": outcome}

    recommendation.status = "rejected"
    recommendation.execution_reason = outcome.get("reason", "Entry trigger could not execute.")
    recommendation.execution_decision = recommendation.execution_reason
    audit(db, current_user, "entry_trigger_rejected", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
    trace_event(
        db,
        current_user,
        event_type="paper_order_rejected",
        status="blocked",
        public_summary=f"{thesis.symbol} paper {entry_action} trigger could not execute.",
        role="Portfolio Manager",
        run_id=thesis.run_id,
        recommendation_id=recommendation.id,
        thesis_id=thesis.id,
        snapshot_id=thesis.snapshot_id,
        exchange=thesis.exchange,
        symbol=thesis.symbol,
        blocker_reason=recommendation.execution_reason,
        evidence={"reason_code": "paper_order_rejected", "result": outcome},
    )
    return {"status": "blocked", "reason": recommendation.execution_reason, "recommendation_id": recommendation.id, "result": outcome}


def _monitor_position_exits(
    db: Session,
    current_user: User,
    account,
    profile,
    now: datetime,
    results: dict[str, Any],
) -> None:
    positions = (
        db.query(PaperPosition)
        .filter(PaperPosition.account_id == account.id, PaperPosition.quantity > 0)
        .order_by(PaperPosition.symbol.asc(), PaperPosition.side.asc())
        .all()
    )
    results["positions_checked"] = len(positions)
    for position in positions:
        price, price_ts = latest_price(db, position.exchange, position.symbol)
        if price is None:
            results["missed"] += 1
            trace_event_once_per_window(
                db,
                current_user,
                window_seconds=300,
                event_type="trigger_waiting",
                status="waiting",
                public_summary=f"{position.symbol} open position is waiting for a fresh market price.",
                role="Trigger Monitor",
                exchange=position.exchange,
                symbol=position.symbol,
                blocker_reason="No latest candle price is available for the open paper position.",
                evidence={"position_id": position.id, "reason_code": "position_price_missing"},
            )
            continue

        position.last_price = price
        repair = _ensure_position_exit_plan(db, current_user, account.id, position, price, price_ts)
        if repair["status"] == "repaired":
            results["repaired"] += 1
            trace_event(
                db,
                current_user,
                event_type="position_exit_repaired",
                status="completed",
                public_summary=f"{position.symbol} {position.side} position exit plan was repaired.",
                role="Trigger Monitor",
                exchange=position.exchange,
                symbol=position.symbol,
                evidence={
                    "reason_code": "position_exit_repaired",
                    "position_id": position.id,
                    "exit_source": repair["source"],
                    "take_profit": position.take_profit,
                    "stop_loss": position.stop_loss,
                    "latest_price": price,
                },
            )
        elif repair["status"] == "missing":
            results["unmanaged"] += 1
            results["missed"] += 1
            trace_event_once_per_window(
                db,
                current_user,
                window_seconds=300,
                event_type="trigger_waiting",
                status="waiting",
                public_summary=f"{position.symbol} open position has no usable exit plan.",
                role="Trigger Monitor",
                exchange=position.exchange,
                symbol=position.symbol,
                blocker_reason=repair["reason"],
                evidence={"position_id": position.id, "reason_code": "position_exit_missing"},
            )
            continue

        _refresh_position_trailing_stop(position, price)
        exit_kind = _position_exit_kind(position, price)
        if exit_kind is None:
            results["missed"] += 1
            trace_event_once_per_window(
                db,
                current_user,
                window_seconds=300,
                event_type="trigger_waiting",
                status="waiting",
                public_summary=f"{position.symbol} position is open; waiting for position-owned exit targets.",
                role="Trigger Monitor",
                exchange=position.exchange,
                symbol=position.symbol,
                blocker_reason="Position take-profit and stop-loss have not crossed yet.",
                evidence={
                    "position_id": position.id,
                    "latest_price": price,
                    "take_profit": position.take_profit,
                    "stop_loss": position.stop_loss,
                    "trailing_peak": position.trailing_peak,
                    "trailing_trough": position.trailing_trough,
                    "reason_code": "position_exit_waiting",
                },
            )
            continue

        executed = _execute_position_exit(
            db,
            current_user,
            account=account,
            profile=profile,
            position=position,
            price=price,
            price_ts=price_ts,
            now=now,
            exit_kind=exit_kind,
        )
        if executed.get("status") == "ok":
            results["executed"] += 1
        else:
            results["blocked"] += 1


def _ensure_position_exit_plan(
    db: Session,
    current_user: User,
    account_id: int,
    position: PaperPosition,
    price: float,
    price_ts: datetime | None,
) -> dict[str, Any]:
    if position.take_profit is not None and position.stop_loss is not None:
        _ensure_position_trailing_seed(position, price)
        return {"status": "managed", "source": "position"}

    thesis, source = _position_exit_context(db, current_user, account_id, position)
    if thesis.take_profit_target is not None and thesis.stop_loss_target is not None:
        position.take_profit = float(thesis.take_profit_target)
        position.stop_loss = float(thesis.stop_loss_target)
        _ensure_position_trailing_seed(position, price)
        return {"status": "repaired", "source": source}

    entry_price = float(position.avg_entry_price or 0.0)
    if entry_price <= 0:
        return {"status": "missing", "reason": "Position average entry price is unavailable."}

    atr = _latest_position_atr(db, position.exchange, position.symbol, price_ts or datetime.now(timezone.utc), entry_price)
    side = "short" if (position.side or "long") == "short" else "long"
    formula_params = formula_parameters_for_user(db, current_user)
    targets = formula_targets(
        entry_price,
        atr,
        side,
        **target_kwargs_for_side(formula_params, side),
    )
    position.take_profit = targets.take_profit
    position.stop_loss = targets.stop_loss
    _ensure_position_trailing_seed(position, price)
    return {"status": "repaired", "source": "formula"}


def _ensure_position_trailing_seed(position: PaperPosition, price: float) -> None:
    entry = float(position.avg_entry_price or price or 0.0)
    if (position.side or "long") == "short":
        if position.trailing_trough is None:
            position.trailing_trough = min(entry, price)
    elif position.trailing_peak is None:
        position.trailing_peak = max(entry, price)


def _refresh_position_trailing_stop(position: PaperPosition, price: float) -> None:
    entry = float(position.avg_entry_price or price or 0.0)
    if (position.side or "long") == "short":
        trough = min(float(position.trailing_trough or entry or price), price)
        position.trailing_trough = trough
        trailing_stop = trough * 1.004
        if position.stop_loss is None or trailing_stop < float(position.stop_loss):
            position.stop_loss = trailing_stop
    else:
        peak = max(float(position.trailing_peak or entry or price), price)
        position.trailing_peak = peak
        trailing_stop = peak * 0.994
        if position.stop_loss is None or trailing_stop > float(position.stop_loss):
            position.stop_loss = trailing_stop


def _position_exit_kind(position: PaperPosition, price: float) -> str | None:
    if (position.side or "long") == "short":
        if position.take_profit is not None and price <= float(position.take_profit):
            return "take_profit"
        if position.stop_loss is not None and price >= float(position.stop_loss):
            return "stop_loss"
        return None
    if position.take_profit is not None and price >= float(position.take_profit):
        return "take_profit"
    if position.stop_loss is not None and price <= float(position.stop_loss):
        return "stop_loss"
    return None


def _execute_position_exit(
    db: Session,
    current_user: User,
    *,
    account,
    profile,
    position: PaperPosition,
    price: float,
    price_ts: datetime | None,
    now: datetime,
    exit_kind: str,
) -> dict[str, Any]:
    thesis, source = _position_exit_context(db, current_user, account.id, position)
    is_short = (position.side or "long") == "short"
    exit_action = "cover" if is_short else "sell"
    recommendation = _trigger_recommendation(db, current_user, thesis, exit_action, price, account.id, price_ts)
    outcome = execute_price_trigger_order(
        db,
        account=account,
        side=exit_action,
        symbol=position.symbol,
        exchange=position.exchange,
        price=price,
        strategy=thesis.strategy_name,
        reason=f"position_{exit_kind}:{position.id}",
        max_position_pct=float(profile.max_position_pct or 0.35),
    )
    if outcome.get("status") != "ok":
        recommendation.status = "rejected"
        recommendation.execution_reason = outcome.get("reason", "Position-owned exit could not execute.")
        recommendation.execution_decision = recommendation.execution_reason
        audit(db, current_user, "position_exit_rejected", {"position_id": position.id, "result": outcome}, recommendation.id)
        trace_event(
            db,
            current_user,
            event_type="paper_order_rejected",
            status="blocked",
            public_summary=f"{position.symbol} paper {exit_action} position-owned exit could not execute.",
            role="Portfolio Manager",
            run_id=thesis.run_id,
            recommendation_id=recommendation.id,
            thesis_id=thesis.id,
            snapshot_id=thesis.snapshot_id,
            exchange=position.exchange,
            symbol=position.symbol,
            blocker_reason=recommendation.execution_reason,
            evidence={
                "reason_code": "position_exit_rejected",
                "position_id": position.id,
                "exit_kind": exit_kind,
                "exit_source": source,
                "result": outcome,
            },
        )
        return {"status": "blocked", "reason": recommendation.execution_reason, "result": outcome}

    if isinstance(thesis, AgentResearchThesis):
        thesis.status = "closed"
        thesis.closed_at = now
    recommendation.status = "executed"
    recommendation.execution_reason = f"Position-owned {exit_kind.replace('_', ' ')} crossed; deterministic paper exit executed."
    recommendation.execution_decision = recommendation.execution_reason
    return_pct = _position_return_pct(position, price)
    _write_lesson(
        db,
        current_user,
        account.id,
        thesis,
        outcome=exit_kind,
        return_pct=return_pct,
        lesson=_exit_lesson(thesis, exit_kind, return_pct),
        recommendation_id=recommendation.id,
    )
    audit(db, current_user, "position_exit_executed", {"position_id": position.id, "result": outcome}, recommendation.id)
    reason_code = "position_take_profit_executed" if exit_kind == "take_profit" else "position_stop_loss_executed"
    if source == "orphan":
        reason_code = "orphan_position_closed"
    trace_event(
        db,
        current_user,
        event_type="paper_order_executed",
        status="executed",
        public_summary=f"{position.symbol} paper {exit_action} executed from position-owned {exit_kind.replace('_', ' ')}.",
        role="Portfolio Manager",
        run_id=thesis.run_id,
        recommendation_id=recommendation.id,
        thesis_id=thesis.id,
        snapshot_id=thesis.snapshot_id,
        exchange=position.exchange,
        symbol=position.symbol,
        rationale=recommendation.execution_reason,
        evidence={
            "reason_code": reason_code,
            "position_id": position.id,
            "exit_kind": exit_kind,
            "exit_source": source,
            "return_pct": return_pct,
            "latest_price": price,
            "result": outcome,
        },
    )
    return {"status": "ok", "result": outcome}


def _position_return_pct(position: PaperPosition, price: float) -> float | None:
    entry = float(position.avg_entry_price or 0.0)
    if entry <= 0:
        return None
    if (position.side or "long") == "short":
        return ((entry - price) / entry) * 100
    return ((price / entry) - 1.0) * 100


def _guardrail_reason_code(reason: str) -> str:
    if "Opposite" in reason and "position is already open" in reason:
        return "opposite_position_blocked"
    return "guardrail_blocked"


def _position_exit_context(
    db: Session,
    current_user: User,
    account_id: int,
    position: PaperPosition,
) -> tuple[AgentResearchThesis | "_PositionThesisContext", str]:
    entry_order = _entry_order_for_position(db, account_id, position)
    if entry_order and entry_order.reason:
        thesis_id = _parse_entry_thesis_id(entry_order.reason)
        if thesis_id is not None:
            thesis = (
                db.query(AgentResearchThesis)
                .filter(AgentResearchThesis.id == thesis_id, AgentResearchThesis.user_id == current_user.id)
                .first()
            )
            if thesis is not None:
                return thesis, "thesis"

    side_values = ("short",) if (position.side or "long") == "short" else ("long", "buy")
    thesis = (
        db.query(AgentResearchThesis)
        .filter(
            AgentResearchThesis.user_id == current_user.id,
            AgentResearchThesis.account_id == account_id,
            AgentResearchThesis.exchange == position.exchange,
            AgentResearchThesis.symbol == position.symbol,
            AgentResearchThesis.side.in_(side_values),
        )
        .order_by(AgentResearchThesis.created_at.desc())
        .first()
    )
    if thesis is not None:
        return thesis, "latest_thesis"

    strategy_name = entry_order.strategy if entry_order and entry_order.strategy else "position_owned_exit"
    side = "short" if (position.side or "long") == "short" else "long"
    return (
        _PositionThesisContext(
            exchange=position.exchange,
            symbol=position.symbol,
            side=side,
            sleeve=side,
            strategy_name=strategy_name,
            confidence=0.5,
            thesis=f"Position-owned paper exit context for orphan {position.symbol} {side} position.",
            take_profit_target=position.take_profit,
            stop_loss_target=position.stop_loss,
        ),
        "orphan",
    )


def _entry_order_for_position(db: Session, account_id: int, position: PaperPosition) -> PaperOrder | None:
    entry_side = PaperOrderSide.SHORT if (position.side or "long") == "short" else PaperOrderSide.BUY
    return (
        db.query(PaperOrder)
        .filter(
            PaperOrder.account_id == account_id,
            PaperOrder.exchange == position.exchange,
            PaperOrder.symbol == position.symbol,
            PaperOrder.side == entry_side,
            PaperOrder.reason.like("entry_trigger:%"),
        )
        .order_by(PaperOrder.timestamp.desc(), PaperOrder.id.desc())
        .first()
    )


def _parse_entry_thesis_id(reason: str) -> int | None:
    prefix = "entry_trigger:"
    if not reason.startswith(prefix):
        return None
    try:
        return int(reason[len(prefix):])
    except (TypeError, ValueError):
        return None


def _latest_position_atr(db: Session, exchange: str, symbol: str, end: datetime, entry_price: float) -> float:
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    try:
        candles = load_candles_df(
            db=db,
            exchange=exchange,
            symbol=symbol,
            start=end - timedelta(minutes=260),
            end=end,
            timeframe="1m",
            source="auto",
            max_points=500,
        )
        if not candles.df.empty:
            formula_df = add_formula_indicators(candles.df)
            atr = float(formula_df.iloc[-1].get("atr") or 0.0)
            if atr > 0:
                return atr
    except Exception:
        return entry_price * 0.01
    return entry_price * 0.01


class _PositionThesisContext:
    id = None
    run_id = None
    recommendation_id = None
    snapshot_id = None
    risk_notes = None
    expires_at = None
    entry_score = None
    exit_score = None
    formula_inputs = {}
    formula_outputs = {}
    strategy_version = "position-exit-v1"
    entry_target = None
    llm_model = None

    def __init__(
        self,
        *,
        exchange: str,
        symbol: str,
        side: str,
        sleeve: str,
        strategy_name: str,
        confidence: float,
        thesis: str,
        take_profit_target: float | None,
        stop_loss_target: float | None,
    ):
        self.exchange = exchange
        self.symbol = symbol
        self.side = side
        self.sleeve = sleeve
        self.strategy_name = strategy_name
        self.confidence = confidence
        self.thesis = thesis
        self.take_profit_target = take_profit_target
        self.stop_loss_target = stop_loss_target


def _to_agent_decision(decision: ThesisDecision) -> AgentDecision:
    return AgentDecision(
        action=decision.action,
        confidence=decision.confidence,
        thesis=decision.thesis,
        risk_notes=decision.risk_notes,
        strategy_name=decision.strategy_name,
        strategy_params=decision.strategy_params,
        side=decision.side,
        sleeve=decision.sleeve,
        entry_score=decision.entry_score,
        exit_score=decision.exit_score,
        formula_inputs=decision.formula_inputs,
        formula_outputs=decision.formula_outputs,
        strategy_version=decision.strategy_version,
        prediction_summary=decision.prediction_summary,
        prediction_horizon_minutes=decision.prediction_horizon_minutes,
        predicted_path=decision.predicted_path,
    )


def _compute_fair_value(signal: dict[str, Any] | None, current_price: float) -> float:
    """Compute a fair value estimate from a weighted average of trend indicators.

    Uses SMA_50, EMA_55, and Bollinger Bands middle band (BBM) when available.
    Falls back to current price if no indicators are present.
    """
    indicators = (signal or {}).get("indicators") or {}
    components: list[tuple[float, float]] = []  # (value, weight)

    sma_50 = indicators.get("sma_50") or indicators.get("SMA_50")
    if sma_50 and float(sma_50) > 0:
        components.append((float(sma_50), 0.35))

    ema_55 = indicators.get("EMA_55")
    if ema_55 and float(ema_55) > 0:
        components.append((float(ema_55), 0.35))

    bbm = indicators.get("bbands_middle") or indicators.get("BBM_20_2.0_2.0")
    if bbm and float(bbm) > 0:
        components.append((float(bbm), 0.30))

    if not components:
        return current_price

    total_weight = sum(w for _, w in components)
    fair_value = sum(v * w for v, w in components) / total_weight
    return fair_value


def _formula_decision_from_snapshot(
    snapshot: dict[str, Any],
    current_price: float | None,
    snapshot_signal: dict[str, Any] | None,
    *,
    reason: str,
) -> ThesisDecision | None:
    if current_price is None or current_price <= 0:
        return None
    formula_metrics = {}
    if isinstance(snapshot_signal, dict):
        formula_metrics = snapshot_signal.get("formula_metrics") or {}
    if not formula_metrics and isinstance(snapshot, dict):
        formula_metrics = snapshot.get("formula_metrics") or {}
    if not isinstance(formula_metrics, dict):
        return None

    long_metrics = formula_metrics.get("long") if isinstance(formula_metrics.get("long"), dict) else {}
    short_metrics = formula_metrics.get("short") if isinstance(formula_metrics.get("short"), dict) else {}
    long_score = float(long_metrics.get("long_entry_score") or 0.0)
    short_score = float(short_metrics.get("short_entry_score") or 0.0)
    if max(long_score, short_score) < FORMULA_ENTRY_SCORE_FLOOR:
        return None

    if short_score > long_score:
        action = "short"
        side = "short"
        score = short_score
        strategy_name = "formula_quick_short"
        sleeve_metrics = short_metrics
    else:
        action = "buy"
        side = "long"
        score = long_score
        strategy_name = "formula_long_momentum"
        sleeve_metrics = long_metrics

    decision = ThesisDecision(
        action=action,
        confidence=max(FORMULA_ENTRY_SCORE_FLOOR, min(0.9, score)),
        thesis=(
            f"Formula-first paper setup selected the {side} sleeve with entry score {score:.2f}. "
            f"{reason}"
        ),
        risk_notes=(
            "Paper-only formula fallback. LLM output is advisory; deterministic ATR/VWAP/RSI/CVD metrics "
            "and guardrails control execution."
        ),
        strategy_name=strategy_name,
        strategy_params={},
        side=side,
        sleeve=side,
        entry_score=score,
        exit_score=float(sleeve_metrics.get(f"{side}_exit_score") or 0.0),
        formula_inputs={},
        formula_outputs={},
        strategy_version="formula-v1",
        entry_condition="immediate",
        entry_target=float(current_price),
        expires_in_minutes=120,
        prediction_summary=f"Formula-first {side} sleeve entry selected from deterministic metrics.",
        prediction_horizon_minutes=240,
        predicted_path=[{"minutes_ahead": 60, "price": float(current_price)}],
    )
    return _compute_fair_value_targets(decision, current_price, snapshot_signal, "aggressive_paper")


def _compute_fair_value_targets(
    decision: ThesisDecision,
    current_price: float | None,
    snapshot_signal: dict[str, Any] | None,
    trade_cadence_mode: str,
) -> ThesisDecision:
    """Apply deterministic formula targets to a model thesis."""
    if current_price is None or current_price <= 0:
        return decision

    price = float(current_price)
    signal = snapshot_signal or {}
    indicators = signal.get("indicators") or {}
    formula_metrics = signal.get("formula_metrics") or {}
    side = "short" if decision.action == "short" or decision.side == "short" else "long"
    sleeve_metrics = formula_metrics.get(side) if isinstance(formula_metrics, dict) else {}
    if not isinstance(sleeve_metrics, dict):
        sleeve_metrics = {}

    atr = sleeve_metrics.get("atr") or indicators.get("atr") or indicators.get("ATRr_14") or price * 0.01
    targets = formula_targets(
        price,
        float(atr or 0.0),
        "short" if side == "short" else "long",
        target_atr_multiplier=1.0 if side == "short" else 2.0,
        min_profit_pct=0.004 if side == "short" else 0.012,
    )
    fair_value = decision.fair_value or _compute_fair_value(signal, price)
    entry_score = (
        decision.entry_score
        if decision.entry_score is not None
        else sleeve_metrics.get("short_entry_score" if side == "short" else "long_entry_score")
    )
    exit_score = (
        decision.exit_score
        if decision.exit_score is not None
        else sleeve_metrics.get("short_exit_score" if side == "short" else "long_exit_score")
    )
    formula_inputs = {
        "atr": targets.atr,
        "vwap": sleeve_metrics.get("vwap"),
        "rsi": sleeve_metrics.get("rsi"),
        "cvd": sleeve_metrics.get("cvd"),
        "cvd_slope": sleeve_metrics.get("cvd_slope"),
        "price_vs_vwap_pct": sleeve_metrics.get("price_vs_vwap_pct"),
        "funding_rate_arbitrage": sleeve_metrics.get("funding_rate_arbitrage")
        or {"enabled": False, "reason": "No futures funding-rate data source is configured."},
    }
    formula_outputs = {
        "entry_score": entry_score,
        "exit_score": exit_score,
        "reward_risk": targets.reward_risk,
        "take_profit": targets.take_profit,
        "stop_loss": targets.stop_loss,
        "sleeve": side,
    }

    return decision.model_copy(
        update={
            "entry_condition": "immediate",
            "fair_value": round(fair_value, 10),
            "entry_target": targets.entry_price,
            "take_profit_target": targets.take_profit,
            "stop_loss_target": targets.stop_loss,
            "side": side,
            "sleeve": side,
            "strategy_name": "formula_quick_short" if side == "short" else "formula_long_momentum",
            "entry_score": float(entry_score or 0.0),
            "exit_score": float(exit_score or 0.0),
            "formula_inputs": formula_inputs,
            "formula_outputs": formula_outputs,
            "strategy_version": "formula-v1",
            "expires_in_minutes": min(180, max(60, int(decision.expires_in_minutes or 120))),
        }
    )


def _raw_json_for_trace(client: OllamaThesisClient) -> dict[str, Any] | None:
    if client.last_parsed_response is not None:
        return client.last_parsed_response
    if client.last_raw_response:
        return {"raw": client.last_raw_response}
    return None


def _llm_timeout_for(role: str, trade_cadence_mode: str) -> int:
    configured = int(settings.CREW_LLM_TIMEOUT_SECONDS or 60)
    if trade_cadence_mode == "aggressive_paper":
        if role == "trade":
            return max(10, min(configured, AGGRESSIVE_TRADE_NOTE_TIMEOUT_SECONDS))
        return max(10, min(configured, AGGRESSIVE_THESIS_TIMEOUT_SECONDS))
    return max(10, configured)


def _formula_first_mode(profile) -> bool:
    return getattr(profile, "trade_cadence_mode", None) == "aggressive_paper"


def _entry_position_pct(profile, recommendation: AgentRecommendation) -> float:
    configured = float(getattr(profile, "max_position_pct", None) or 0.35)
    if not _formula_first_mode(profile) or recommendation.action not in {"buy", "short"}:
        return configured
    score = recommendation.entry_score
    if score is None:
        outputs = recommendation.formula_outputs or {}
        score = outputs.get("entry_score")
    try:
        entry_score = float(score or 0.0)
    except (TypeError, ValueError):
        entry_score = 0.0
    full_size_score = FORMULA_FULL_SIZE_SCORE
    outputs = recommendation.formula_outputs or {}
    try:
        full_size_score = float(outputs.get("full_size_score") or outputs.get("entry_full_size_score") or full_size_score)
    except (TypeError, ValueError):
        full_size_score = FORMULA_FULL_SIZE_SCORE
    if entry_score < full_size_score:
        return min(configured, 0.05)
    return configured


def _commit_progress(db: Session, *objects: Any) -> None:
    heartbeat = datetime.now(timezone.utc).isoformat()
    for obj in objects:
        if isinstance(obj, AgentRun):
            obj.summary = {**(obj.summary or {}), "heartbeat_at": heartbeat}
    db.commit()
    for obj in objects:
        if obj is not None:
            try:
                db.refresh(obj)
            except Exception:
                pass


class _LessonStubThesis:
    def __init__(self, *, run_id: int, snapshot_id: int, exchange: str, symbol: str, strategy_name: str, confidence: float):
        self.id = None
        self.run_id = run_id
        self.snapshot_id = snapshot_id
        self.exchange = exchange
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.confidence = confidence


def _lesson_stub_thesis(
    *,
    run_id: int,
    snapshot_id: int,
    exchange: str,
    symbol: str,
    strategy_name: str,
    confidence: float,
) -> _LessonStubThesis:
    return _LessonStubThesis(
        run_id=run_id,
        snapshot_id=snapshot_id,
        exchange=exchange,
        symbol=symbol,
        strategy_name=strategy_name,
        confidence=confidence,
    )


def _position_for_thesis(db: Session, account_id: int, thesis: AgentResearchThesis) -> PaperPosition | None:
    return (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id == account_id,
            PaperPosition.exchange == thesis.exchange,
            PaperPosition.symbol == thesis.symbol,
            PaperPosition.side == ("short" if thesis.side == "short" else "long"),
            PaperPosition.quantity > 0,
        )
        .first()
    )



def _entry_crossed(thesis: AgentResearchThesis, price: float) -> bool:
    # Immediate fair-value entries fire unconditionally -- the thesis already
    # determined the current price is at or below fair value.
    if thesis.entry_condition == "immediate":
        return True
    if thesis.entry_target is None:
        return False
    if thesis.entry_condition == "at_or_above":
        return price >= thesis.entry_target
    return price <= thesis.entry_target


def _exit_crossed(thesis: AgentResearchThesis, price: float) -> bool:
    if thesis.side == "short":
        if thesis.take_profit_target is not None and price <= thesis.take_profit_target:
            return True
        if thesis.stop_loss_target is not None and price >= thesis.stop_loss_target:
            return True
        return False
    if thesis.take_profit_target is not None and price >= thesis.take_profit_target:
        return True
    if thesis.stop_loss_target is not None and price <= thesis.stop_loss_target:
        return True
    return False


def _write_lesson(
    db: Session,
    current_user: User,
    account_id: int,
    thesis: AgentResearchThesis,
    *,
    outcome: str,
    return_pct: float | None,
    lesson: str,
    recommendation_id: int | None = None,
) -> None:
    db.add(
        AgentLesson(
            user_id=current_user.id,
            account_id=account_id,
            thesis_id=getattr(thesis, "id", None),
            recommendation_id=recommendation_id,
            symbol=thesis.symbol,
            strategy_name=thesis.strategy_name,
            outcome=outcome,
            return_pct=return_pct,
            confidence=thesis.confidence,
            lesson=lesson,
        )
    )
    db.flush()
    if outcome in {"take_profit", "stop_loss", "paper_sell", "paper_cover", "win", "loss"}:
        maybe_create_formula_suggestion(db, current_user, source=f"lesson:{outcome}")


def _exit_lesson(thesis: AgentResearchThesis, outcome: str, return_pct: float | None) -> str:
    return_text = f"{return_pct:.2f}%" if return_pct is not None else "unknown return"
    if outcome == "take_profit":
        return f"{thesis.symbol} reached take-profit with {return_text}; preserve this target discipline for similar setups."
    return f"{thesis.symbol} hit stop-loss with {return_text}; future theses should tighten entry quality or reduce sizing for this setup."


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _thesis_payload(row: AgentResearchThesis) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "run_id": row.run_id,
        "snapshot_id": row.snapshot_id,
        "recommendation_id": row.recommendation_id,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "strategy_params": row.strategy_params or {},
        "side": row.side,
        "sleeve": getattr(row, "sleeve", None),
        "confidence": row.confidence,
        "thesis": row.thesis,
        "risk_notes": row.risk_notes,
        "entry_condition": row.entry_condition,
        "entry_target": row.entry_target,
        "take_profit_target": row.take_profit_target,
        "stop_loss_target": row.stop_loss_target,
        "latest_observed_price": row.latest_observed_price,
        "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "triggered_at": row.triggered_at.isoformat() if row.triggered_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "lessons_used": row.lessons_used or [],
        "metadata": row.metadata_json or {},
        "model_role": row.model_role,
        "llm_model": row.llm_model,
        "entry_score": getattr(row, "entry_score", None),
        "exit_score": getattr(row, "exit_score", None),
        "formula_inputs": getattr(row, "formula_inputs", None) or {},
        "formula_outputs": getattr(row, "formula_outputs", None) or {},
        "strategy_version": getattr(row, "strategy_version", None),
        "created_at": utc_isoformat(row.created_at),
        "updated_at": utc_isoformat(row.updated_at),
    }


def _build_thesis_prompt(
    snapshot: dict[str, Any],
    lessons: list[dict[str, Any]],
    *,
    trade_cadence_mode: str = "standard",
) -> str:
    cadence_instruction = ""
    if trade_cadence_mode == "aggressive_paper":
        cadence_instruction = (
            "AGGRESSIVE PAPER CADENCE IS ACTIVE. You MUST follow these rules:\n"
            "1. If formula_metrics.long has the stronger entry score, choose action=buy with side=long.\n"
            "2. If formula_metrics.short has the stronger entry score, choose action=short with side=short.\n"
            "3. Only reject if data is stale/missing or both sleeve scores are weak.\n"
            "4. This is paper-only simulation. Your job is to trade clear formula setups, not wait.\n"
        )
    return (
        "You are a local autonomous crypto paper-trading strategist for a dual-sleeve AI crew. "
        "All execution is paper-only. The bankroll is split 50% long momentum and 50% paper short. "
        "Use the deterministic formula_metrics from the snapshot for math; your role is thesis, risk review, "
        "notes, and adaptation from lessons.\n\n"
        "FORMULA MODEL:\n"
        "- Long sleeve: buy coins going up when ATR/VWAP/RSI/CVD confirm momentum.\n"
        "- Short sleeve: open conservative 1x paper shorts when ATR/VWAP/RSI/CVD confirm downside.\n"
        "- Funding-rate arbitrage is visible but disabled until a futures funding data source exists.\n"
        "- Favor stronger walk-forward Sortino, positive expectancy, acceptable drawdown, and recent lessons.\n\n"
        "ENTRY RULES:\n"
        '- entry_condition MUST always be "immediate". We do NOT wait for price dips.\n'
        "- entry_target = the current market price (execute now).\n"
        "- Use action=buy, side=long, sleeve=long for formula_long_momentum.\n"
        "- Use action=short, side=short, sleeve=short for formula_quick_short.\n\n"
        "EXIT RULES:\n"
        "- Long take_profit_target is above entry and stop_loss_target is below entry.\n"
        "- Short take_profit_target is below entry and stop_loss_target is above entry.\n"
        "- Backend recomputes deterministic ATR targets; include the formula values in formula_inputs and formula_outputs.\n\n"
        "Return ONLY VALID JSON matching this schema exactly. "
        "DO NOT INCLUDE COMMENTS (like //) OR EXPLANATIONS INSIDE OR OUTSIDE THE JSON.\n"
        "{"
        '"action":"buy|short|hold|reject",'
        '"confidence":0.0,'
        '"thesis":"evidence-based reason referencing formula_metrics and lessons",'
        '"risk_notes":"risk summary",'
        '"strategy_name":"formula_long_momentum|formula_quick_short",'
        '"strategy_params":{},'
        '"side":"long|short",'
        '"sleeve":"long|short",'
        '"entry_score":0.0,'
        '"exit_score":0.0,'
        '"formula_inputs":{},'
        '"formula_outputs":{},'
        '"strategy_version":"formula-v1",'
        '"entry_condition":"immediate",'
        '"fair_value":123.45,'
        '"entry_target":123.45,'
        '"take_profit_target":130.0,'
        '"stop_loss_target":119.0,'
        '"expires_in_minutes":120,'
        '"prediction_summary":"short expected path",'
        '"prediction_horizon_minutes":240,'
        '"predicted_path":[{"minutes_ahead":60,"price":123.45}]'
        "}\n\n"
        'IMPORTANT: entry_condition MUST be "immediate". '
        "Use reject ONLY for stale data or weak formula scores. Prefer buying strength or shorting confirmed downside.\n"
        f"{cadence_instruction}\n"
        "PAST TRADE LESSONS (learn from these and adapt your strategy):\n"
        f"{json.dumps(lessons, default=str)}\n\n"
        "CURRENT MARKET SNAPSHOT:\n"
        f"{json.dumps(snapshot, default=str)}"
    )


def _build_trade_decision_prompt(
    thesis: AgentResearchThesis,
    recommendation: AgentRecommendation,
    action: str,
    price: float,
) -> str:
    payload = {
        "action": action,
        "side": thesis.side,
        "sleeve": getattr(thesis, "sleeve", None),
        "exchange": thesis.exchange,
        "symbol": thesis.symbol,
        "latest_price": price,
        "entry_condition": thesis.entry_condition,
        "entry_target": thesis.entry_target,
        "take_profit_target": thesis.take_profit_target,
        "stop_loss_target": thesis.stop_loss_target,
        "confidence": thesis.confidence,
        "strategy_name": thesis.strategy_name,
        "strategy_params": thesis.strategy_params or {},
        "entry_score": getattr(thesis, "entry_score", None),
        "exit_score": getattr(thesis, "exit_score", None),
        "formula_inputs": getattr(thesis, "formula_inputs", None) or {},
        "formula_outputs": getattr(thesis, "formula_outputs", None) or {},
        "strategy_version": getattr(thesis, "strategy_version", None),
        "thesis": thesis.thesis,
        "risk_notes": thesis.risk_notes,
        "backtest_summary": recommendation.backtest_summary or {},
        "source_data_timestamp": recommendation.source_data_timestamp.isoformat()
        if recommendation.source_data_timestamp
        else None,
    }
    return (
        "You are the trade decision model for a local crypto paper-trading team. "
        "A price trigger has crossed. Approve only if the action is consistent with the thesis, "
        "the target logic is coherent, and the trade remains paper-only. Backend guardrails have already passed, "
        "but your approval is still required. Return only JSON matching this schema: "
        "{"
        '"decision":"approve|reject",'
        '"confidence":0.0,'
        '"rationale":"short reason",'
        '"risk_notes":"optional risk notes"'
        "}. Trigger context:\n"
        f"{json.dumps(payload, default=str)}"
    )
