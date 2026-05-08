from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.research import AgentTraceEvent
from app.models.user import User


def trace_event(
    db: Session,
    current_user: User,
    *,
    event_type: str,
    status: str,
    public_summary: str,
    role: str = "System",
    run_id: int | None = None,
    recommendation_id: int | None = None,
    thesis_id: int | None = None,
    snapshot_id: int | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    rationale: str | None = None,
    blocker_reason: str | None = None,
    evidence: dict[str, Any] | None = None,
    prompt: str | None = None,
    raw_model_json: dict[str, Any] | list[Any] | None = None,
    validation_error: str | None = None,
    model_role: str | None = None,
    llm_model: str | None = None,
) -> AgentTraceEvent:
    event = AgentTraceEvent(
        user_id=current_user.id,
        run_id=run_id,
        recommendation_id=recommendation_id,
        thesis_id=thesis_id,
        snapshot_id=snapshot_id,
        role=role,
        exchange=exchange,
        symbol=symbol,
        event_type=event_type,
        status=status,
        public_summary=public_summary[:4000],
        rationale=rationale[:4000] if rationale else None,
        blocker_reason=blocker_reason[:4000] if blocker_reason else None,
        evidence_json=evidence or {},
        prompt=prompt,
        raw_model_json=raw_model_json,
        validation_error=validation_error[:4000] if validation_error else None,
        model_role=model_role,
        llm_model=llm_model,
    )
    db.add(event)
    db.flush()
    return event


def trace_event_once_per_window(
    db: Session,
    current_user: User,
    *,
    window_seconds: int,
    event_type: str,
    status: str,
    public_summary: str,
    role: str = "System",
    run_id: int | None = None,
    recommendation_id: int | None = None,
    thesis_id: int | None = None,
    snapshot_id: int | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    rationale: str | None = None,
    blocker_reason: str | None = None,
    evidence: dict[str, Any] | None = None,
    prompt: str | None = None,
    raw_model_json: dict[str, Any] | list[Any] | None = None,
    validation_error: str | None = None,
    model_role: str | None = None,
    llm_model: str | None = None,
) -> AgentTraceEvent:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=max(1, window_seconds))
    existing = (
        db.query(AgentTraceEvent)
        .filter(
            AgentTraceEvent.user_id == current_user.id,
            AgentTraceEvent.event_type == event_type,
            AgentTraceEvent.status == status,
            AgentTraceEvent.role == role,
            AgentTraceEvent.symbol == symbol,
            AgentTraceEvent.blocker_reason == blocker_reason,
            AgentTraceEvent.created_at >= cutoff,
        )
        .order_by(AgentTraceEvent.created_at.desc())
        .first()
    )
    if existing is not None:
        return existing
    return trace_event(
        db,
        current_user,
        event_type=event_type,
        status=status,
        public_summary=public_summary,
        role=role,
        run_id=run_id,
        recommendation_id=recommendation_id,
        thesis_id=thesis_id,
        snapshot_id=snapshot_id,
        exchange=exchange,
        symbol=symbol,
        rationale=rationale,
        blocker_reason=blocker_reason,
        evidence=evidence,
        prompt=prompt,
        raw_model_json=raw_model_json,
        validation_error=validation_error,
        model_role=model_role,
        llm_model=llm_model,
    )


def trace_payload(row: AgentTraceEvent, *, debug: bool = False) -> dict[str, Any]:
    evidence = row.evidence_json or {}
    payload = {
        "id": row.id,
        "run_id": row.run_id,
        "recommendation_id": row.recommendation_id,
        "thesis_id": row.thesis_id,
        "snapshot_id": row.snapshot_id,
        "role": row.role,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "event_type": row.event_type,
        "status": row.status,
        "public_summary": row.public_summary,
        "rationale": row.rationale,
        "blocker_reason": row.blocker_reason,
        "reason_code": evidence.get("reason_code") or _reason_code(row.event_type, row.status),
        "evidence": evidence,
        "validation_error": row.validation_error,
        "model_role": row.model_role,
        "llm_model": row.llm_model,
        "created_at": utc_isoformat(row.created_at),
    }
    if debug:
        payload["prompt"] = row.prompt
        payload["raw_model_json"] = row.raw_model_json
    return payload


def _reason_code(event_type: str, status: str) -> str:
    if event_type == "guardrail_blocked":
        return "guardrail_blocked"
    mapping = {
        "research_queued": "research_queued",
        "research_started": "research_running",
        "research_completed": "research_completed",
        "research_blocked": "research_blocked",
        "agent_output_rejected": "llm_output_rejected",
        "llm_formula_fallback": "llm_timeout_formula_fallback",
        "thesis_created": "active_thesis",
        "trigger_waiting": "no_active_thesis" if status == "waiting" else "trigger_waiting",
        "guardrail_blocked": "guardrail_blocked",
        "trade_decision_failed": "trade_note_failed",
        "trade_decision_rejected": "trade_note_failed",
        "paper_order_executed": "formula_entry_executed",
        "paper_order_rejected": "paper_order_rejected",
        "trigger_expired": "expired",
        "position_exit_repaired": "position_exit_repaired",
    }
    return mapping.get(event_type, event_type)


def utc_isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
