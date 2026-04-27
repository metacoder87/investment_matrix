from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models.research import AgentGuardrailProfile, AgentModelInvocation
from app.models.user import User


MODEL_ROUTE_FIELDS = {
    "default": "default_llm_model",
    "research": "research_llm_model",
    "thesis": "thesis_llm_model",
    "risk": "risk_llm_model",
    "trade": "trade_llm_model",
}

MODEL_ROLE_LABELS = {
    "default": "Global Default",
    "research": "Market Research",
    "thesis": "Thesis Strategist",
    "risk": "Risk Review",
    "trade": "Trade Decision",
}


def normalized_role(role: str | None) -> str:
    value = (role or "default").strip().lower().replace("_", "-")
    if value in {"global", "global-default"}:
        return "default"
    if value in {"strategy", "thesis-strategy", "thesis_strategy"}:
        return "thesis"
    if value in {"trading", "trade-decision", "trade_decision"}:
        return "trade"
    return value if value in MODEL_ROUTE_FIELDS else "default"


def effective_model(profile: AgentGuardrailProfile | None, role: str = "default") -> str:
    route = normalized_role(role)
    if profile is not None:
        role_model = getattr(profile, MODEL_ROUTE_FIELDS[route], None)
        if role_model:
            return str(role_model)
        default_model = getattr(profile, "default_llm_model", None)
        if default_model:
            return str(default_model)
    return settings.CREW_LLM_MODEL


def model_routing_payload(profile: AgentGuardrailProfile | None) -> dict[str, Any]:
    selected = {
        role: (getattr(profile, field, None) if profile is not None else None)
        for role, field in MODEL_ROUTE_FIELDS.items()
    }
    return {
        "roles": [
            {
                "role": role,
                "label": MODEL_ROLE_LABELS[role],
                "selected_model": selected[role],
                "effective_model": effective_model(profile, role),
                "uses_default": not bool(selected[role]),
            }
            for role in MODEL_ROUTE_FIELDS
        ],
        "selected": selected,
        "effective": {role: effective_model(profile, role) for role in MODEL_ROUTE_FIELDS},
        "fallback_model": settings.CREW_LLM_MODEL,
    }


def apply_model_routing(profile: AgentGuardrailProfile, payload: dict[str, str | None]) -> None:
    for role, field in MODEL_ROUTE_FIELDS.items():
        if role not in payload:
            continue
        value = payload[role]
        clean = value.strip() if isinstance(value, str) else None
        setattr(profile, field, clean or None)


def ollama_models() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": bool(settings.CREW_ENABLED),
        "provider": settings.CREW_LLM_PROVIDER,
        "base_url": settings.CREW_LLM_BASE_URL,
        "models": [],
        "available": False,
        "status": "disabled" if not settings.CREW_ENABLED else "checking",
        "message": "Crew runtime is disabled.",
    }
    if settings.CREW_LLM_PROVIDER.strip().lower() != "ollama":
        payload["status"] = "unsupported_provider"
        payload["message"] = "Only the Ollama provider is supported in this local-first phase."
        return payload
    try:
        response = requests.get(f"{settings.CREW_LLM_BASE_URL.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        models = []
        for row in response.json().get("models", []):
            details = row.get("details") or {}
            name = row.get("name") or row.get("model")
            if not name:
                continue
            models.append(
                {
                    "name": name,
                    "model": row.get("model") or name,
                    "modified_at": row.get("modified_at"),
                    "size": row.get("size"),
                    "family": details.get("family"),
                    "parameter_size": details.get("parameter_size"),
                    "quantization_level": details.get("quantization_level"),
                }
            )
        payload.update(
            {
                "models": sorted(models, key=lambda item: str(item["name"]).lower()),
                "available": True,
                "status": "available",
                "message": "Ollama runtime is reachable.",
            }
        )
    except Exception as exc:
        payload["status"] = "unavailable"
        payload["message"] = f"Ollama is not reachable: {exc}"
    return payload


def runtime_payload(profile: AgentGuardrailProfile | None = None, *, role: str = "default") -> dict[str, Any]:
    if not settings.CREW_ENABLED:
        return {
            "enabled": False,
            "provider": settings.CREW_LLM_PROVIDER,
            "base_url": settings.CREW_LLM_BASE_URL,
            "model": effective_model(profile, role),
            "selected_model": effective_model(profile, role),
            "available": False,
            "status": "disabled",
            "message": "Crew runtime is disabled. Set CREW_ENABLED=true and configure Ollama to run agent cycles.",
            "model_available": None,
            "model_routing": model_routing_payload(profile),
        }
    payload = ollama_models()
    model = effective_model(profile, role)
    payload["model"] = model
    payload["selected_model"] = model
    payload["model_routing"] = model_routing_payload(profile)
    if payload["available"]:
        names = {item["name"] for item in payload["models"]}
        payload["model_available"] = model in names if names else None
        if names and model not in names:
            payload["status"] = "model_missing"
            payload["available"] = False
            payload["message"] = f"Selected model {model} is not downloaded in Ollama."
    return payload


def ensure_model_exists(model: str, models_payload: dict[str, Any] | None = None) -> None:
    payload = models_payload or ollama_models()
    if not payload.get("available"):
        raise ValueError(payload.get("message") or "Ollama is unavailable.")
    names = {row["name"] for row in payload.get("models", [])}
    if model not in names:
        raise ValueError(f"Model {model} is not downloaded in Ollama.")


def start_model_invocation(
    db: Session,
    current_user: User,
    *,
    role: str,
    action_type: str,
    model: str,
    run_id: int | None = None,
    recommendation_id: int | None = None,
    thesis_id: int | None = None,
    snapshot_id: int | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    timeout_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentModelInvocation:
    now = datetime.now(timezone.utc)
    row = AgentModelInvocation(
        user_id=current_user.id,
        run_id=run_id,
        recommendation_id=recommendation_id,
        thesis_id=thesis_id,
        snapshot_id=snapshot_id,
        role=MODEL_ROLE_LABELS.get(normalized_role(role), role),
        action_type=action_type,
        llm_provider=settings.CREW_LLM_PROVIDER,
        llm_base_url=settings.CREW_LLM_BASE_URL,
        llm_model=model,
        exchange=exchange,
        symbol=symbol,
        status="running",
        timeout_seconds=timeout_seconds,
        started_at=now,
        metadata_json=metadata or {},
    )
    db.add(row)
    db.flush()
    return row


def complete_model_invocation(
    db: Session,
    invocation: AgentModelInvocation,
    *,
    status: str,
    error_message: str | None = None,
    validation_error: str | None = None,
    response_summary: str | None = None,
    raw_model_json: dict[str, Any] | list[Any] | None = None,
    recommendation_id: int | None = None,
    thesis_id: int | None = None,
    paper_order_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    completed = datetime.now(timezone.utc)
    invocation.status = status
    invocation.completed_at = completed
    if invocation.started_at:
        started = invocation.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        invocation.latency_ms = int((completed - started).total_seconds() * 1000)
    invocation.error_message = error_message[:4000] if error_message else None
    invocation.validation_error = validation_error[:4000] if validation_error else None
    invocation.response_summary = response_summary[:4000] if response_summary else None
    invocation.raw_model_json = raw_model_json
    if recommendation_id is not None:
        invocation.recommendation_id = recommendation_id
    if thesis_id is not None:
        invocation.thesis_id = thesis_id
    if paper_order_id is not None:
        invocation.paper_order_id = paper_order_id
    if metadata:
        merged = dict(invocation.metadata_json or {})
        merged.update(metadata)
        invocation.metadata_json = merged
    db.flush()


def invoke_ollama_json(
    db: Session,
    current_user: User,
    *,
    role: str,
    action_type: str,
    model: str,
    prompt: str,
    run_id: int | None = None,
    recommendation_id: int | None = None,
    thesis_id: int | None = None,
    snapshot_id: int | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    timeout_seconds: int | None = None,
    temperature: float = 0.1,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, AgentModelInvocation]:
    timeout_value = int(timeout_seconds or max(10, settings.CREW_LLM_TIMEOUT_SECONDS))
    invocation = start_model_invocation(
        db,
        current_user,
        role=role,
        action_type=action_type,
        model=model,
        run_id=run_id,
        recommendation_id=recommendation_id,
        thesis_id=thesis_id,
        snapshot_id=snapshot_id,
        exchange=exchange,
        symbol=symbol,
        timeout_seconds=timeout_value,
        metadata=metadata,
    )
    try:
        response = requests.post(
            f"{settings.CREW_LLM_BASE_URL.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature},
            },
            timeout=timeout_value,
        )
        response.raise_for_status()
        raw = response.json().get("response")
        if not raw:
            raise ValueError("Ollama returned an empty JSON response.")
        
        # Pre-process raw string to aggressively strip out hallucinated inline comments
        raw = re.sub(r'(?m)//.*$', '', raw)
        
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Ollama JSON response must be an object.")
        complete_model_invocation(
            db,
            invocation,
            status="success",
            raw_model_json=parsed,
            response_summary=_summarize_response(parsed),
        )
        return parsed, raw, invocation
    except requests.Timeout as exc:
        complete_model_invocation(db, invocation, status="timeout", error_message=str(exc))
        raise
    except json.JSONDecodeError as exc:
        complete_model_invocation(db, invocation, status="invalid_json", validation_error=str(exc))
        raise ValueError("Model response was not valid JSON.") from exc
    except Exception as exc:
        status = "error"
        if isinstance(exc, ValueError):
            status = "invalid_response"
        complete_model_invocation(db, invocation, status=status, error_message=str(exc))
        raise


def mark_invocation_validation_failed(db: Session, invocation: AgentModelInvocation, error: str) -> None:
    complete_model_invocation(db, invocation, status="validation_failed", validation_error=error)


def test_model_json(
    db: Session,
    current_user: User,
    *,
    role: str,
    model: str,
) -> dict[str, Any]:
    prompt = (
        'Return only JSON exactly like {"status":"ok","model_test":true,"reason":"ready"}. '
        "No markdown, no prose."
    )
    timeout_seconds = max(10, int(settings.CREW_LLM_TIMEOUT_SECONDS or 60))
    try:
        parsed, _, invocation = invoke_ollama_json(
            db,
            current_user,
            role=role,
            action_type="model_test",
            model=model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            metadata={"probe": True},
        )
        ok = parsed.get("status") == "ok" and parsed.get("model_test") is True
        if not ok:
            mark_invocation_validation_failed(db, invocation, "Probe returned JSON but not the required status/model_test fields.")
        return {
            "ok": ok,
            "status": "ok" if ok else "invalid_json_contract",
            "model": model,
            "role": normalized_role(role),
            "latency_ms": invocation.latency_ms,
            "valid_json": True,
            "message": "Model returned valid probe JSON." if ok else "Model returned JSON that did not match the probe contract.",
        }
    except requests.Timeout as exc:
        return {
            "ok": False,
            "status": "timeout",
            "model": model,
            "role": normalized_role(role),
            "latency_ms": None,
            "valid_json": False,
            "message": f"Model timed out after {timeout_seconds} seconds: {exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "model": model,
            "role": normalized_role(role),
            "latency_ms": None,
            "valid_json": False,
            "message": str(exc),
        }


def _summarize_response(parsed: dict[str, Any]) -> str:
    for key in ("action", "status", "decision", "thesis", "reason", "rationale"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:4000]
    return json.dumps(parsed, default=str)[:4000]
