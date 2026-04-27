from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models.paper import PaperPosition
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
from app.services.crew_models import (
    complete_model_invocation,
    effective_model,
    invoke_ollama_json,
    mark_invocation_validation_failed,
    model_routing_payload,
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
from app.services.market_resolution import configured_exchange_priority


class ThesisDecision(BaseModel):
    action: Literal["buy", "hold", "reject"] = "hold"
    confidence: float = Field(ge=0, le=1)
    thesis: str = Field(min_length=5, max_length=4000)
    risk_notes: str | None = Field(default=None, max_length=4000)
    strategy_name: str = "sma_cross"
    strategy_params: dict[str, Any] = Field(default_factory=lambda: {"short_window": 20, "long_window": 50})
    entry_condition: Literal["at_or_below", "at_or_above"] = "at_or_below"
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
        prompt = _build_thesis_prompt(snapshot, lessons, trade_cadence_mode=trade_cadence_mode)
        def _invoke(current_prompt: str):
            self.last_prompt = current_prompt
            self.last_raw_response = None
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
                    timeout_seconds=max(10, settings.CREW_LLM_TIMEOUT_SECONDS),
                )
            else:
                response = requests.post(
                    f"{settings.CREW_LLM_BASE_URL.rstrip('/')}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": current_prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1},
                    },
                    timeout=max(10, settings.CREW_LLM_TIMEOUT_SECONDS),
                )
                response.raise_for_status()
                raw = response.json().get("response")
                if not raw:
                    raise ValueError("Ollama returned an empty thesis response.")
                import re
                raw = re.sub(r'(?m)//.*$', '', raw)
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError("Agent thesis response was not valid JSON.") from exc
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
            timeout_seconds=max(10, settings.CREW_LLM_TIMEOUT_SECONDS),
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
) -> dict[str, Any]:
    profile = get_or_create_guardrails(db, current_user)
    thesis_model = effective_model(profile, "thesis")
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
    if not status["enabled"] or not status["available"]:
        audit(db, current_user, "autonomous_research_unavailable", {"runtime": status})
        trace_event(
            db,
            current_user,
            event_type="research_blocked",
            status="blocked",
            public_summary="Autonomous research skipped because the local LLM runtime is unavailable.",
            role="Market Data Auditor",
            blocker_reason=status.get("message", "Crew runtime unavailable."),
            evidence={"runtime": status},
        )
        return {"status": "unavailable", "runtime": status}

    account = get_or_create_ai_account(db, current_user)
    max_count = max(1, min(max_symbols or settings.CREW_MAX_SYMBOLS_PER_RUN, settings.CREW_MAX_SYMBOLS_PER_RUN))
    run = AgentRun(
        user_id=current_user.id,
        status="running",
        mode="autonomous_research",
        llm_provider=settings.CREW_LLM_PROVIDER,
        llm_base_url=settings.CREW_LLM_BASE_URL,
        llm_model=thesis_model,
        max_symbols=max_count,
        requested_symbols=[],
        selected_symbols=[],
        summary={"agents": AGENT_ROLES, "mode": "autonomous_research"},
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
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
            "trade_cadence_mode": profile.trade_cadence_mode or "aggressive_paper",
            "runtime": status,
            "model_routing": model_routing_payload(profile),
            "llm_model": thesis_model,
        },
    )

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
    client = OllamaThesisClient(model=thesis_model, db=db, current_user=current_user, run=run)
    lessons = recent_lessons_for_prompt(db, current_user)
    created = 0
    rejected = 0
    selected: list[str] = []
    consecutive_timeouts = 0
    stopped_reason: str | None = None

    for asset in assets:
        snapshot = _build_snapshot(db, current_user, run, asset)
        if snapshot is None:
            continue
        selected.append(snapshot.symbol)
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
            },
        )
        try:
            thesis_decision = client.generate_thesis(
                snapshot.snapshot,
                lessons,
                trade_cadence_mode=profile.trade_cadence_mode or "aggressive_paper",
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
            )
            thesis_decision = _apply_aggressive_paper_targets(
                thesis_decision,
                snapshot.price,
                profile.trade_cadence_mode or "aggressive_paper",
            )
        except Exception as exc:
            rejected += 1
            is_timeout = isinstance(exc, requests.Timeout) or "timed out" in str(exc).lower()
            consecutive_timeouts = consecutive_timeouts + 1 if is_timeout else 0
            audit(
                db,
                current_user,
                "agent_thesis_rejected",
                {"run_id": run.id, "snapshot_id": snapshot.id, "symbol": snapshot.symbol, "reason": str(exc)},
            )
            trace_event(
                db,
                current_user,
                event_type="agent_output_rejected",
                status="failed",
                public_summary=f"{snapshot.symbol} thesis output failed validation.",
                role="Portfolio Manager",
                run_id=run.id,
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
                blocker_reason=str(exc),
                prompt=client.last_prompt,
                raw_model_json=_raw_json_for_trace(client),
                validation_error=str(exc),
                model_role="thesis",
                llm_model=thesis_model,
            )
            if consecutive_timeouts >= 3:
                stopped_reason = (
                    f"Thesis model {thesis_model} timed out {consecutive_timeouts} times in a row. "
                    "Research stopped early; choose a faster local model or increase the model timeout."
                )
                trace_event(
                    db,
                    current_user,
                    event_type="research_blocked_model_timeout",
                    status="blocked",
                    public_summary="Research stopped early because the selected thesis model repeatedly timed out.",
                    role="Market Data Auditor",
                    run_id=run.id,
                    blocker_reason=stopped_reason,
                    evidence={
                        "consecutive_timeouts": consecutive_timeouts,
                        "llm_model": thesis_model,
                        "selected_symbols": selected,
                    },
                    model_role="thesis",
                    llm_model=thesis_model,
                )
                break
            continue

        consecutive_timeouts = 0

        if thesis_decision.action != "buy":
            rejected += 1
            audit(
                db,
                current_user,
                "agent_thesis_no_trade_plan",
                {"run_id": run.id, "symbol": snapshot.symbol, "action": thesis_decision.action},
            )
            trace_event(
                db,
                current_user,
                event_type="thesis_rejected",
                status="blocked",
                public_summary=f"{snapshot.symbol} did not receive an actionable buy thesis.",
                role="Portfolio Manager",
                run_id=run.id,
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
                rationale=thesis_decision.thesis,
                blocker_reason=f"Agent action was {thesis_decision.action}.",
                evidence={"confidence": thesis_decision.confidence, "risk_notes": thesis_decision.risk_notes},
                prompt=client.last_prompt,
                raw_model_json=client.last_parsed_response,
                model_role="thesis",
                llm_model=thesis_model,
            )
            continue

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
            model_role="thesis",
            llm_model=thesis_model,
        )
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
                evidence=backtest_summary,
            )
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
                evidence=backtest_summary,
            )
            rejected += 1
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
            model_role="thesis",
            llm_model=thesis_model,
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
                "llm_model": thesis_model,
                "model_role": "thesis",
            },
            prompt=client.last_prompt,
            raw_model_json=client.last_parsed_response,
            model_role="thesis",
            llm_model=thesis_model,
        )

    run.status = "completed"
    run.selected_symbols = selected
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {
        "runtime": status,
        "agents": AGENT_ROLES,
        "selected": selected,
        "theses_created": created,
        "rejected": rejected,
        "stopped_reason": stopped_reason,
        "model_routing": model_routing_payload(profile),
        "llm_model": thesis_model,
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
        evidence=run.summary,
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
    profile = get_or_create_guardrails(db, current_user)
    thesis_model = effective_model(profile, "thesis")
    status = runtime_status()
    run = AgentRun(
        user_id=current_user.id,
        status="running",
        mode="research_dry_run",
        llm_provider=settings.CREW_LLM_PROVIDER,
        llm_base_url=settings.CREW_LLM_BASE_URL,
        llm_model=thesis_model,
        max_symbols=1,
        requested_symbols=[symbol] if symbol else [],
        selected_symbols=[],
        summary={"mode": "research_dry_run", "model_routing": model_routing_payload(profile)},
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    if not status.get("enabled") or not status.get("available"):
        run.status = "failed"
        run.error_message = status.get("message", "Crew runtime unavailable.")
        run.completed_at = datetime.now(timezone.utc)
        trace_event(
            db,
            current_user,
            event_type="research_dry_run_blocked",
            status="blocked",
            public_summary="Research dry-run could not start because the model runtime is unavailable.",
            role="Market Data Auditor",
            run_id=run.id,
            blocker_reason=run.error_message,
            evidence={"runtime": status},
            model_role="thesis",
            llm_model=thesis_model,
        )
        db.commit()
        return {
            "ok": False,
            "status": "runtime_unavailable",
            "run_id": run.id,
            "model": thesis_model,
            "message": run.error_message,
        }

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
            model_role="thesis",
            llm_model=thesis_model,
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
    client = OllamaThesisClient(model=thesis_model, db=db, current_user=current_user, run=run)
    lessons = recent_lessons_for_prompt(db, current_user)
    trace_event(
        db,
        current_user,
        event_type="research_dry_run_started",
        status="running",
        public_summary=f"Testing {thesis_model} against one {snapshot.exchange.upper()} thesis snapshot.",
        role="Market Data Auditor",
        run_id=run.id,
        snapshot_id=snapshot.id,
        exchange=snapshot.exchange,
        symbol=snapshot.symbol,
        evidence={"row_count": snapshot.row_count, "price": snapshot.price},
        model_role="thesis",
        llm_model=thesis_model,
    )

    try:
        decision = client.generate_thesis(
            snapshot.snapshot,
            lessons,
            trade_cadence_mode=profile.trade_cadence_mode or "aggressive_paper",
            snapshot_id=snapshot.id,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
        )
        decision = _apply_aggressive_paper_targets(
            decision,
            snapshot.price,
            profile.trade_cadence_mode or "aggressive_paper",
        )
    except requests.Timeout as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        trace_event(
            db,
            current_user,
            event_type="research_dry_run_failed",
            status="blocked",
            public_summary=f"{thesis_model} timed out during the thesis dry-run.",
            role="Thesis Strategist",
            run_id=run.id,
            snapshot_id=snapshot.id,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            blocker_reason=str(exc),
            prompt=client.last_prompt,
            model_role="thesis",
            llm_model=thesis_model,
        )
        db.commit()
        return {
            "ok": False,
            "status": "timeout",
            "run_id": run.id,
            "model": thesis_model,
            "symbol": snapshot.symbol,
            "exchange": snapshot.exchange,
            "message": str(exc),
        }
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        trace_event(
            db,
            current_user,
            event_type="research_dry_run_failed",
            status="blocked",
            public_summary=f"{thesis_model} failed the thesis dry-run validation.",
            role="Thesis Strategist",
            run_id=run.id,
            snapshot_id=snapshot.id,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            blocker_reason=str(exc),
            validation_error=str(exc),
            prompt=client.last_prompt,
            raw_model_json=_raw_json_for_trace(client),
            model_role="thesis",
            llm_model=thesis_model,
        )
        db.commit()
        return {
            "ok": False,
            "status": "failed",
            "run_id": run.id,
            "model": thesis_model,
            "symbol": snapshot.symbol,
            "exchange": snapshot.exchange,
            "message": str(exc),
            "raw_model_json": _raw_json_for_trace(client),
        }

    payload = decision.model_dump(mode="json")
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {
        "mode": "research_dry_run",
        "symbol": snapshot.symbol,
        "exchange": snapshot.exchange,
        "llm_model": thesis_model,
        "decision": payload,
    }
    trace_event(
        db,
        current_user,
        event_type="research_dry_run_completed",
        status="completed",
        public_summary=f"{thesis_model} produced a valid {snapshot.symbol} thesis dry-run.",
        role="Thesis Strategist",
        run_id=run.id,
        snapshot_id=snapshot.id,
        exchange=snapshot.exchange,
        symbol=snapshot.symbol,
        rationale=decision.thesis,
        evidence=payload,
        prompt=client.last_prompt,
        raw_model_json=client.last_parsed_response,
        model_role="thesis",
        llm_model=thesis_model,
    )
    db.commit()
    return {
        "ok": True,
        "status": "ok",
        "run_id": run.id,
        "model": thesis_model,
        "symbol": snapshot.symbol,
        "exchange": snapshot.exchange,
        "message": "Model produced a valid thesis JSON payload.",
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
    results = {"status": "ok", "checked": len(theses), "executed": 0, "blocked": 0, "expired": 0, "missed": 0}
    if not theses:
        trace_event_once_per_window(
            db,
            current_user,
            window_seconds=300,
            event_type="trigger_waiting",
            status="waiting",
            public_summary="Trigger monitor is running but no active theses are available.",
            role="Trigger Monitor",
            blocker_reason="No active or entry-triggered thesis records.",
        )

    for thesis in theses:
        expires_at = _as_aware(thesis.expires_at)
        if expires_at and expires_at <= now:
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
            recommendation = _trigger_recommendation(db, current_user, thesis, "buy", price, account.id, price_ts)
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
                    evidence={"latest_price": price, "entry_target": thesis.entry_target},
                )
                continue

            approved, decision_reason, trade_model, invocation = _review_trigger_trade(
                db,
                current_user,
                profile,
                thesis,
                recommendation,
                "buy",
                price,
            )
            if not approved:
                recommendation.status = "rejected"
                recommendation.execution_reason = decision_reason
                recommendation.execution_decision = decision_reason
                recommendation.trade_decision_model = trade_model
                results["blocked"] += 1
                _write_lesson(
                    db,
                    current_user,
                    account.id,
                    thesis,
                    outcome="trade_decision_blocked",
                    return_pct=None,
                    lesson=f"{thesis.symbol} entry trigger was blocked by the trade decision model: {decision_reason}",
                    recommendation_id=recommendation.id,
                )
                continue

            outcome = execute_price_trigger_order(
                db,
                account=account,
                side="buy",
                symbol=thesis.symbol,
                exchange=thesis.exchange,
                price=price,
                strategy=thesis.strategy_name,
                reason=f"entry_trigger:{thesis.id}",
                max_position_pct=float(profile.max_position_pct or 0.35),
            )
            if outcome.get("status") == "ok":
                if invocation is not None and outcome.get("order", {}).get("id"):
                    invocation.paper_order_id = outcome["order"]["id"]
                thesis.status = "entry_triggered"
                thesis.triggered_at = now
                recommendation.status = "executed"
                recommendation.execution_reason = "Entry target crossed and guardrails passed."
                recommendation.execution_decision = recommendation.execution_reason
                results["executed"] += 1
                _write_lesson(
                    db,
                    current_user,
                    account.id,
                    thesis,
                    outcome="paper_buy",
                    return_pct=None,
                    lesson=f"{thesis.symbol} entry executed at {price:.8g}; monitor take-profit and stop-loss discipline.",
                    recommendation_id=recommendation.id,
                )
                audit(db, current_user, "entry_trigger_executed", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="paper_order_executed",
                    status="executed",
                    public_summary=f"{thesis.symbol} paper buy executed after entry trigger crossed.",
                    role="Portfolio Manager",
                    run_id=thesis.run_id,
                    recommendation_id=recommendation.id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    rationale=recommendation.execution_reason,
                    evidence={"result": outcome, "latest_price": price, "entry_target": thesis.entry_target},
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
                    public_summary=f"{thesis.symbol} paper buy trigger could not execute.",
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

        if position is not None and _exit_crossed(thesis, price):
            outcome_name = "take_profit" if thesis.take_profit_target and price >= thesis.take_profit_target else "stop_loss"
            recommendation = _trigger_recommendation(db, current_user, thesis, "sell", price, account.id, price_ts)
            allowed, reason = check_guardrails(db, current_user, profile, recommendation)
            if not allowed:
                recommendation.status = "rejected"
                recommendation.execution_reason = reason
                recommendation.execution_decision = reason
                results["blocked"] += 1
                audit(db, current_user, "exit_trigger_blocked", {"thesis_id": thesis.id, "reason": reason}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="guardrail_blocked",
                    status="blocked",
                    public_summary=f"{thesis.symbol} exit trigger crossed but was blocked.",
                    role="Risk Manager",
                    run_id=thesis.run_id,
                    recommendation_id=recommendation.id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    blocker_reason=reason,
                    evidence={
                        "latest_price": price,
                        "take_profit_target": thesis.take_profit_target,
                        "stop_loss_target": thesis.stop_loss_target,
                    },
                )
                continue

            approved, decision_reason, trade_model, invocation = _review_trigger_trade(
                db,
                current_user,
                profile,
                thesis,
                recommendation,
                "sell",
                price,
            )
            if not approved:
                recommendation.status = "rejected"
                recommendation.execution_reason = decision_reason
                recommendation.execution_decision = decision_reason
                recommendation.trade_decision_model = trade_model
                results["blocked"] += 1
                audit(db, current_user, "trade_decision_blocked", {"thesis_id": thesis.id, "reason": decision_reason}, recommendation.id)
                continue

            avg_entry = float(position.avg_entry_price or 0.0)
            return_pct = ((price / avg_entry) - 1.0) * 100 if avg_entry > 0 else None
            outcome = execute_price_trigger_order(
                db,
                account=account,
                side="sell",
                symbol=thesis.symbol,
                exchange=thesis.exchange,
                price=price,
                strategy=thesis.strategy_name,
                reason=f"{outcome_name}:{thesis.id}",
                max_position_pct=float(profile.max_position_pct or 0.35),
            )
            if outcome.get("status") == "ok":
                if invocation is not None and outcome.get("order", {}).get("id"):
                    invocation.paper_order_id = outcome["order"]["id"]
                thesis.status = "closed"
                thesis.closed_at = now
                recommendation.status = "executed"
                recommendation.execution_reason = f"{outcome_name.replace('_', ' ').title()} target crossed and guardrails passed."
                recommendation.execution_decision = recommendation.execution_reason
                results["executed"] += 1
                _write_lesson(
                    db,
                    current_user,
                    account.id,
                    thesis,
                    outcome=outcome_name,
                    return_pct=return_pct,
                    lesson=_exit_lesson(thesis, outcome_name, return_pct),
                    recommendation_id=recommendation.id,
                )
                audit(db, current_user, "exit_trigger_executed", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="paper_order_executed",
                    status="executed",
                    public_summary=f"{thesis.symbol} paper sell executed on {outcome_name.replace('_', ' ')}.",
                    role="Portfolio Manager",
                    run_id=thesis.run_id,
                    recommendation_id=recommendation.id,
                    thesis_id=thesis.id,
                    snapshot_id=thesis.snapshot_id,
                    exchange=thesis.exchange,
                    symbol=thesis.symbol,
                    rationale=recommendation.execution_reason,
                    evidence={"result": outcome, "return_pct": return_pct, "latest_price": price},
                )
            else:
                recommendation.status = "rejected"
                recommendation.execution_reason = outcome.get("reason", "Exit trigger could not execute.")
                recommendation.execution_decision = recommendation.execution_reason
                results["blocked"] += 1
                audit(db, current_user, "exit_trigger_rejected", {"thesis_id": thesis.id, "result": outcome}, recommendation.id)
                trace_event(
                    db,
                    current_user,
                    event_type="paper_order_rejected",
                    status="blocked",
                    public_summary=f"{thesis.symbol} paper sell trigger could not execute.",
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
        elif position is not None:
            results["missed"] += 1
            trace_event(
                db,
                current_user,
                event_type="trigger_waiting",
                status="waiting",
                public_summary=f"{thesis.symbol} position is open; waiting for take-profit or stop-loss.",
                role="Trigger Monitor",
                run_id=thesis.run_id,
                recommendation_id=thesis.recommendation_id,
                thesis_id=thesis.id,
                snapshot_id=thesis.snapshot_id,
                exchange=thesis.exchange,
                symbol=thesis.symbol,
                blocker_reason="Exit target has not crossed yet.",
                evidence={
                    "latest_price": price,
                    "take_profit_target": thesis.take_profit_target,
                    "stop_loss_target": thesis.stop_loss_target,
                },
            )

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
    entry_target = decision.entry_target
    if entry_target is None:
        entry_target = current_price * (0.995 if decision.entry_condition == "at_or_below" else 1.005)
    take_profit = decision.take_profit_target or entry_target * 1.04
    stop_loss = decision.stop_loss_target or entry_target * 0.97

    (
        db.query(AgentResearchThesis)
        .filter(
            AgentResearchThesis.user_id == current_user.id,
            AgentResearchThesis.account_id == account_id,
            AgentResearchThesis.exchange == exchange,
            AgentResearchThesis.symbol == symbol,
            AgentResearchThesis.status.in_(("active", "entry_triggered")),
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
        side="buy",
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
    recommendation = AgentRecommendation(
        user_id=current_user.id,
        agent_name="Trigger Monitor",
        strategy_name=thesis.strategy_name,
        exchange=thesis.exchange,
        symbol=thesis.symbol,
        action=action,
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
        evidence_json={
            "thesis_id": thesis.id,
            "trigger_price": price,
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


def _to_agent_decision(decision: ThesisDecision) -> AgentDecision:
    return AgentDecision(
        action="buy",
        confidence=decision.confidence,
        thesis=decision.thesis,
        risk_notes=decision.risk_notes,
        strategy_name=decision.strategy_name,
        strategy_params=decision.strategy_params,
        prediction_summary=decision.prediction_summary,
        prediction_horizon_minutes=decision.prediction_horizon_minutes,
        predicted_path=decision.predicted_path,
    )


def _apply_aggressive_paper_targets(
    decision: ThesisDecision,
    current_price: float | None,
    trade_cadence_mode: str,
) -> ThesisDecision:
    if trade_cadence_mode != "aggressive_paper" or current_price is None or current_price <= 0:
        return decision
    price = float(current_price)
    entry = decision.entry_target or price
    if abs(entry - price) / price > 0.005:
        entry = price * 1.005
    take_profit = decision.take_profit_target or entry * 1.02
    take_profit_pct = (take_profit / entry) - 1.0
    if take_profit_pct < 0.015 or take_profit_pct > 0.03:
        take_profit = entry * 1.02
    stop_loss = decision.stop_loss_target or entry * 0.985
    stop_loss_pct = 1.0 - (stop_loss / entry)
    if stop_loss_pct < 0.01 or stop_loss_pct > 0.025:
        stop_loss = entry * 0.985
        
    if abs(take_profit - stop_loss) < (price * 0.01):
        take_profit = entry * 1.01
        stop_loss = entry * 0.99
    return decision.model_copy(
        update={
            "entry_condition": "at_or_below",
            "entry_target": round(entry, 10),
            "take_profit_target": round(take_profit, 10),
            "stop_loss_target": round(stop_loss, 10),
            "expires_in_minutes": min(120, max(60, int(decision.expires_in_minutes or 90))),
        }
    )


def _raw_json_for_trace(client: OllamaThesisClient) -> dict[str, Any] | None:
    if client.last_parsed_response is not None:
        return client.last_parsed_response
    if client.last_raw_response:
        return {"raw": client.last_raw_response}
    return None


def _position_for_thesis(db: Session, account_id: int, thesis: AgentResearchThesis) -> PaperPosition | None:
    return (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id == account_id,
            PaperPosition.exchange == thesis.exchange,
            PaperPosition.symbol == thesis.symbol,
            PaperPosition.quantity > 0,
        )
        .first()
    )


def _entry_crossed(thesis: AgentResearchThesis, price: float) -> bool:
    if thesis.entry_target is None:
        return False
    if thesis.entry_condition == "at_or_above":
        return price >= thesis.entry_target
    return price <= thesis.entry_target


def _exit_crossed(thesis: AgentResearchThesis, price: float) -> bool:
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
            thesis_id=thesis.id,
            recommendation_id=recommendation_id,
            symbol=thesis.symbol,
            strategy_name=thesis.strategy_name,
            outcome=outcome,
            return_pct=return_pct,
            confidence=thesis.confidence,
            lesson=lesson,
        )
    )


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
            "Aggressive paper cadence is active: propose near-market entries only. "
            "Entry must be within 0.5% of current price, take-profit must be 1.5% to 3% from entry, "
            "stop-loss must be 1% to 2.5% from entry, and expiry must be 60 to 120 minutes. "
            "This is simulation only, but missing backtest or stale data must still be rejected. "
        )
    return (
        "You are a local autonomous crypto paper-trading team. Create a standing trade thesis, not an immediate trade. "
        "Return ONLY VALID JSON matching this schema exactly. DO NOT INCLUDE COMMENTS (like //) OR EXPLANATIONS INSIDE OR OUTSIDE THE JSON payload. "
        "{"
        '"action":"buy|hold|reject",'
        '"confidence":0.0,'
        '"thesis":"evidence-based reason",'
        '"risk_notes":"risk summary",'
        '"strategy_name":"sma_cross|rsi|buy_hold",'
        '"strategy_params":{},'
        '"entry_condition":"at_or_below|at_or_above",'
        '"entry_target":123.45,'
        '"take_profit_target":130.0,'
        '"stop_loss_target":119.0,'
        '"expires_in_minutes":240,'
        '"prediction_summary":"short expected path",'
        '"prediction_horizon_minutes":240,'
        '"predicted_path":[{"minutes_ahead":60,"price":123.45}]'
        "}. Use reject for weak or stale data. Prefer aggressive paper-only setups, but targets must be plausible. "
        f"{cadence_instruction}"
        "Recent lessons:\n"
        f"{json.dumps(lessons, default=str)}\n"
        "Snapshot:\n"
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
