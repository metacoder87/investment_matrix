from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.models.research import AgentFormulaConfig, AgentFormulaSuggestion, AgentLesson
from app.models.user import User
from app.trading.formulas import DEFAULT_SCORING_WEIGHTS, formula_targets


FORMULA_ENGINE_MODEL = "deterministic-formula-v1"
AUTHORITY_APPROVAL_REQUIRED = "approval_required"
AUTHORITY_AUTO_APPLY_BOUNDED = "auto_apply_bounded"
VALID_AUTHORITY_MODES = {AUTHORITY_APPROVAL_REQUIRED, AUTHORITY_AUTO_APPLY_BOUNDED}

DEFAULT_FORMULA_PARAMETERS: dict[str, Any] = {
    "version": "formula-v1",
    "entry_score_floor": 0.50,
    "full_size_score": 0.60,
    "exit_score_floor": 0.55,
    "atr_length": 14,
    "rsi_length": 14,
    "cvd_length": 20,
    "stop_atr_multiplier": 1.5,
    "max_stop_pct": 0.03,
    "long": {
        "entry_threshold": 0.50,
        "exit_threshold": 0.55,
        "target_atr_multiplier": 2.0,
        "min_profit_pct": 0.012,
        "trailing_stop_pct": 0.006,
    },
    "short": {
        "entry_threshold": 0.50,
        "exit_threshold": 0.55,
        "target_atr_multiplier": 1.4,
        "min_profit_pct": 0.006,
        "trailing_stop_pct": 0.004,
    },
    "guardrails": {
        "aggressive_min_backtest_return_pct": -10.0,
        "aggressive_max_drawdown_pct": -25.0,
    },
    "scoring_weights": DEFAULT_SCORING_WEIGHTS,
}

DEFAULT_FORMULA_BOUNDS: dict[str, dict[str, float]] = {
    "entry_score_floor": {"min": 0.10, "max": 0.95},
    "full_size_score": {"min": 0.10, "max": 0.95},
    "exit_score_floor": {"min": 0.10, "max": 0.95},
    "atr_length": {"min": 2, "max": 120},
    "rsi_length": {"min": 2, "max": 120},
    "cvd_length": {"min": 1, "max": 240},
    "stop_atr_multiplier": {"min": 0.25, "max": 6.0},
    "max_stop_pct": {"min": 0.001, "max": 0.20},
    "long.entry_threshold": {"min": 0.10, "max": 0.95},
    "long.exit_threshold": {"min": 0.10, "max": 0.95},
    "long.target_atr_multiplier": {"min": 0.25, "max": 8.0},
    "long.min_profit_pct": {"min": 0.001, "max": 0.20},
    "long.trailing_stop_pct": {"min": 0.001, "max": 0.10},
    "short.entry_threshold": {"min": 0.10, "max": 0.95},
    "short.exit_threshold": {"min": 0.10, "max": 0.95},
    "short.target_atr_multiplier": {"min": 0.25, "max": 8.0},
    "short.min_profit_pct": {"min": 0.001, "max": 0.20},
    "short.trailing_stop_pct": {"min": 0.001, "max": 0.10},
    "guardrails.aggressive_min_backtest_return_pct": {"min": -100.0, "max": 100.0},
    "guardrails.aggressive_max_drawdown_pct": {"min": -100.0, "max": 0.0},
}


def deterministic_runtime_payload() -> dict[str, Any]:
    return {
        "enabled": True,
        "available": True,
        "provider": "formula",
        "base_url": None,
        "model": FORMULA_ENGINE_MODEL,
        "selected_model": FORMULA_ENGINE_MODEL,
        "model_available": True,
        "status": "available",
        "message": "Deterministic formula crew is available. Optional AI notes do not block trading.",
    }


def get_or_create_formula_config(db: Session, current_user: User) -> AgentFormulaConfig:
    rows = (
        db.query(AgentFormulaConfig)
        .filter(AgentFormulaConfig.user_id == current_user.id, AgentFormulaConfig.is_active.is_(True))
        .order_by(AgentFormulaConfig.updated_at.desc(), AgentFormulaConfig.id.desc())
        .all()
    )
    config = rows[0] if rows else None
    for stale in rows[1:]:
        stale.is_active = False
    if config is None:
        config = AgentFormulaConfig(
            user_id=current_user.id,
            name="Formula v1",
            is_active=True,
            parameters_json=deepcopy(DEFAULT_FORMULA_PARAMETERS),
            bounds_json=deepcopy(DEFAULT_FORMULA_BOUNDS),
            authority_mode=AUTHORITY_APPROVAL_REQUIRED,
            created_by="system",
        )
        db.add(config)
        db.flush()
        return config

    config.parameters_json = normalise_formula_parameters(config.parameters_json or {}, config.bounds_json or DEFAULT_FORMULA_BOUNDS)
    config.bounds_json = normalise_formula_bounds(config.bounds_json or {})
    if config.authority_mode not in VALID_AUTHORITY_MODES:
        config.authority_mode = AUTHORITY_APPROVAL_REQUIRED
    db.flush()
    return config


def formula_parameters_for_user(db: Session, current_user: User) -> dict[str, Any]:
    config = get_or_create_formula_config(db, current_user)
    return normalise_formula_parameters(config.parameters_json or {}, config.bounds_json or DEFAULT_FORMULA_BOUNDS)


def formula_config_payload(config: AgentFormulaConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name,
        "is_active": bool(config.is_active),
        "authority_mode": config.authority_mode or AUTHORITY_APPROVAL_REQUIRED,
        "created_by": config.created_by,
        "parameters": normalise_formula_parameters(config.parameters_json or {}, config.bounds_json or DEFAULT_FORMULA_BOUNDS),
        "bounds": normalise_formula_bounds(config.bounds_json or {}),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def update_formula_config(
    db: Session,
    current_user: User,
    *,
    name: str | None = None,
    authority_mode: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    bounds: Mapping[str, Any] | None = None,
) -> AgentFormulaConfig:
    config = get_or_create_formula_config(db, current_user)
    if name is not None and name.strip():
        config.name = name.strip()[:120]
    if authority_mode is not None:
        clean_mode = authority_mode.strip().lower()
        if clean_mode not in VALID_AUTHORITY_MODES:
            raise ValueError("authority_mode must be approval_required or auto_apply_bounded.")
        config.authority_mode = clean_mode
    if bounds is not None:
        config.bounds_json = normalise_formula_bounds(bounds)
    if parameters is not None:
        merged = _deep_merge(normalise_formula_parameters(config.parameters_json or {}, config.bounds_json or {}), parameters)
        config.parameters_json = normalise_formula_parameters(merged, config.bounds_json or DEFAULT_FORMULA_BOUNDS)
    config.created_by = config.created_by or "user"
    db.flush()
    return config


def formula_decision_from_snapshot(
    snapshot: dict[str, Any],
    current_price: float | None,
    snapshot_signal: dict[str, Any] | None,
    *,
    parameters: Mapping[str, Any] | None = None,
    reason: str = "Deterministic formula crew selected this setup.",
) -> dict[str, Any] | None:
    params = normalise_formula_parameters(parameters or {}, DEFAULT_FORMULA_BOUNDS)
    if current_price is None or current_price <= 0:
        return None

    formula_metrics = _formula_metrics(snapshot, snapshot_signal)
    if not formula_metrics:
        return None

    long_metrics = formula_metrics.get("long") if isinstance(formula_metrics.get("long"), dict) else {}
    short_metrics = formula_metrics.get("short") if isinstance(formula_metrics.get("short"), dict) else {}
    long_score = _float(long_metrics.get("long_entry_score"))
    short_score = _float(short_metrics.get("short_entry_score"))
    floor = _float(params.get("entry_score_floor"), 0.50)
    if max(long_score, short_score) < floor:
        return None

    if short_score > long_score:
        side = "short"
        action = "short"
        strategy_name = "formula_quick_short"
        score = short_score
        sleeve_metrics = short_metrics
        exit_score = _float(short_metrics.get("short_exit_score"))
    else:
        side = "long"
        action = "buy"
        strategy_name = "formula_long_momentum"
        score = long_score
        sleeve_metrics = long_metrics
        exit_score = _float(long_metrics.get("long_exit_score"))

    price = float(current_price)
    targets = formula_targets(price, _float(sleeve_metrics.get("atr"), price * 0.01), side, **target_kwargs_for_side(params, side))
    fair_value = _compute_fair_value(snapshot_signal, price)
    strategy_params = strategy_params_for_side(params, side)
    formula_inputs = {
        "atr": targets.atr,
        "vwap": sleeve_metrics.get("vwap"),
        "rsi": sleeve_metrics.get("rsi"),
        "cvd": sleeve_metrics.get("cvd"),
        "cvd_slope": sleeve_metrics.get("cvd_slope"),
        "price_vs_vwap_pct": sleeve_metrics.get("price_vs_vwap_pct"),
        "entry_score_floor": floor,
        "full_size_score": params.get("full_size_score"),
        "funding_rate_arbitrage": sleeve_metrics.get("funding_rate_arbitrage")
        or {"enabled": False, "reason": "No futures funding-rate data source is configured."},
    }
    formula_outputs = {
        "entry_score": round(score, 4),
        "exit_score": round(exit_score, 4),
        "reward_risk": targets.reward_risk,
        "take_profit": targets.take_profit,
        "stop_loss": targets.stop_loss,
        "sleeve": side,
        "entry_score_floor": floor,
        "full_size_score": params.get("full_size_score"),
        "strategy_parameters": strategy_params,
    }
    return {
        "action": action,
        "confidence": max(floor, min(0.9, score)),
        "thesis": f"Formula-only {side} setup selected with entry score {score:.2f}. {reason}",
        "risk_notes": (
            "Paper-only deterministic decision. ATR/VWAP/RSI/CVD metrics, backtest proof, "
            "and guardrails control execution; AI notes are non-blocking."
        ),
        "strategy_name": strategy_name,
        "strategy_params": strategy_params,
        "side": side,
        "sleeve": side,
        "entry_score": round(score, 4),
        "exit_score": round(exit_score, 4),
        "formula_inputs": formula_inputs,
        "formula_outputs": formula_outputs,
        "strategy_version": params.get("version") or "formula-v1",
        "entry_condition": "immediate",
        "fair_value": round(fair_value, 10),
        "entry_target": targets.entry_price,
        "take_profit_target": targets.take_profit,
        "stop_loss_target": targets.stop_loss,
        "expires_in_minutes": 120,
        "prediction_summary": f"Formula-only {side} sleeve selected from deterministic metrics.",
        "prediction_horizon_minutes": 240,
        "predicted_path": [
            {"minutes_ahead": 60, "price": targets.entry_price},
            {"minutes_ahead": 240, "price": targets.take_profit},
        ],
    }


def strategy_params_for_side(parameters: Mapping[str, Any], side: str) -> dict[str, Any]:
    params = normalise_formula_parameters(parameters, DEFAULT_FORMULA_BOUNDS)
    side_params = params.get("short" if side == "short" else "long") or {}
    return {
        "atr_length": int(params.get("atr_length") or 14),
        "rsi_length": int(params.get("rsi_length") or 14),
        "cvd_length": int(params.get("cvd_length") or 20),
        "entry_threshold": float(side_params.get("entry_threshold") or params.get("entry_score_floor") or 0.50),
        "exit_threshold": float(side_params.get("exit_threshold") or params.get("exit_score_floor") or 0.55),
        "stop_atr_multiplier": float(params.get("stop_atr_multiplier") or 1.5),
        "target_atr_multiplier": float(side_params.get("target_atr_multiplier") or (1.4 if side == "short" else 2.0)),
        "min_profit_pct": float(side_params.get("min_profit_pct") or (0.006 if side == "short" else 0.012)),
        "max_stop_pct": float(params.get("max_stop_pct") or 0.03),
        "scoring_weights": deepcopy(params.get("scoring_weights") or DEFAULT_SCORING_WEIGHTS),
    }


def target_kwargs_for_side(parameters: Mapping[str, Any], side: str) -> dict[str, float]:
    params = normalise_formula_parameters(parameters, DEFAULT_FORMULA_BOUNDS)
    side_params = params.get("short" if side == "short" else "long") or {}
    return {
        "stop_atr_multiplier": float(params.get("stop_atr_multiplier") or 1.5),
        "target_atr_multiplier": float(side_params.get("target_atr_multiplier") or (1.4 if side == "short" else 2.0)),
        "min_profit_pct": float(side_params.get("min_profit_pct") or (0.006 if side == "short" else 0.012)),
        "max_stop_pct": float(params.get("max_stop_pct") or 0.03),
    }


def normalise_formula_parameters(raw: Mapping[str, Any] | None, bounds: Mapping[str, Any] | None = None) -> dict[str, Any]:
    params = _deep_merge(DEFAULT_FORMULA_PARAMETERS, raw or {})
    bound_map = normalise_formula_bounds(bounds or {})
    for path, limits in bound_map.items():
        current = _get_path(params, path)
        if current is None:
            continue
        _set_path(params, path, _clamp_number(current, limits["min"], limits["max"]))
    params["atr_length"] = int(round(float(params["atr_length"])))
    params["rsi_length"] = int(round(float(params["rsi_length"])))
    params["cvd_length"] = int(round(float(params["cvd_length"])))
    params["scoring_weights"] = _normalise_scoring_weights(params.get("scoring_weights"))
    params["version"] = str(params.get("version") or "formula-v1")
    return params


def normalise_formula_bounds(raw: Mapping[str, Any] | None) -> dict[str, dict[str, float]]:
    bounds = deepcopy(DEFAULT_FORMULA_BOUNDS)
    if not isinstance(raw, Mapping):
        return bounds
    for path, limits in raw.items():
        if path not in bounds or not isinstance(limits, Mapping):
            continue
        min_value = _float(limits.get("min"), bounds[path]["min"])
        max_value = _float(limits.get("max"), bounds[path]["max"])
        if min_value > max_value:
            min_value, max_value = max_value, min_value
        bounds[path] = {"min": min_value, "max": max_value}
    return bounds


def list_formula_suggestions(db: Session, current_user: User, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        db.query(AgentFormulaSuggestion)
        .filter(AgentFormulaSuggestion.user_id == current_user.id)
        .order_by(AgentFormulaSuggestion.created_at.desc(), AgentFormulaSuggestion.id.desc())
        .limit(limit)
        .all()
    )
    return [formula_suggestion_payload(row) for row in rows]


def formula_suggestion_payload(row: AgentFormulaSuggestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "config_id": row.config_id,
        "status": row.status,
        "source": row.source,
        "proposed_parameters": row.proposed_parameters_json or {},
        "deterministic_evidence": row.deterministic_evidence_json or {},
        "ai_notes": row.ai_notes,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def approve_formula_suggestion(db: Session, current_user: User, suggestion_id: int) -> AgentFormulaSuggestion | None:
    suggestion = _suggestion_for_user(db, current_user, suggestion_id)
    if suggestion is None:
        return None
    if suggestion.status not in {"pending", "auto_applied"}:
        return suggestion
    config = get_or_create_formula_config(db, current_user)
    config.parameters_json = normalise_formula_parameters(
        suggestion.proposed_parameters_json or {},
        config.bounds_json or DEFAULT_FORMULA_BOUNDS,
    )
    suggestion.status = "approved"
    suggestion.applied_at = datetime.now(timezone.utc)
    _supersede_other_pending_suggestions(db, current_user, suggestion.id)
    db.flush()
    return suggestion


def reject_formula_suggestion(db: Session, current_user: User, suggestion_id: int) -> AgentFormulaSuggestion | None:
    suggestion = _suggestion_for_user(db, current_user, suggestion_id)
    if suggestion is None:
        return None
    if suggestion.status == "pending":
        suggestion.status = "rejected"
    db.flush()
    return suggestion


def maybe_create_formula_suggestion(
    db: Session,
    current_user: User,
    *,
    source: str = "closed_trade",
    min_closed_trades: int = 3,
) -> AgentFormulaSuggestion | None:
    config = get_or_create_formula_config(db, current_user)
    lessons = (
        db.query(AgentLesson)
        .filter(
            AgentLesson.user_id == current_user.id,
            AgentLesson.return_pct.isnot(None),
            AgentLesson.outcome.in_(("take_profit", "stop_loss", "paper_sell", "paper_cover", "win", "loss")),
        )
        .order_by(AgentLesson.created_at.desc(), AgentLesson.id.desc())
        .limit(30)
        .all()
    )
    if len(lessons) < min_closed_trades:
        return None

    returns = [float(row.return_pct or 0.0) for row in lessons]
    wins = [value for value in returns if value > 0]
    avg_return = sum(returns) / len(returns)
    win_rate = len(wins) / len(returns)
    current = normalise_formula_parameters(config.parameters_json or {}, config.bounds_json or DEFAULT_FORMULA_BOUNDS)
    proposed = deepcopy(current)
    notes: list[str] = []

    if avg_return < 0 or win_rate < 0.45:
        proposed["entry_score_floor"] = round(float(proposed["entry_score_floor"]) + 0.02, 4)
        proposed["long"]["entry_threshold"] = round(float(proposed["long"]["entry_threshold"]) + 0.02, 4)
        proposed["short"]["entry_threshold"] = round(float(proposed["short"]["entry_threshold"]) + 0.02, 4)
        notes.append("Recent closed trades underperformed; tighten entry thresholds.")
    elif win_rate >= 0.60 and avg_return > 0:
        proposed["entry_score_floor"] = round(float(proposed["entry_score_floor"]) - 0.01, 4)
        proposed["long"]["target_atr_multiplier"] = round(float(proposed["long"]["target_atr_multiplier"]) + 0.05, 4)
        proposed["short"]["target_atr_multiplier"] = round(float(proposed["short"]["target_atr_multiplier"]) + 0.05, 4)
        notes.append("Recent closed trades were profitable; modestly expand opportunity and targets.")
    else:
        return None

    proposed = normalise_formula_parameters(proposed, config.bounds_json or DEFAULT_FORMULA_BOUNDS)
    if proposed == current:
        return None
    pending_same = (
        db.query(AgentFormulaSuggestion)
        .filter(
            AgentFormulaSuggestion.user_id == current_user.id,
            AgentFormulaSuggestion.status == "pending",
            AgentFormulaSuggestion.proposed_parameters_json == proposed,
        )
        .first()
    )
    if pending_same is not None:
        return pending_same

    evidence = {
        "closed_trade_count": len(returns),
        "win_rate": round(win_rate, 4),
        "avg_return_pct": round(avg_return, 4),
        "latest_returns_pct": returns[:10],
        "source": source,
    }
    status = "pending"
    applied_at = None
    if config.authority_mode == AUTHORITY_AUTO_APPLY_BOUNDED:
        config.parameters_json = proposed
        status = "auto_applied"
        applied_at = datetime.now(timezone.utc)
        _supersede_other_pending_suggestions(db, current_user, None)
    suggestion = AgentFormulaSuggestion(
        user_id=current_user.id,
        config_id=config.id,
        status=status,
        source=source,
        proposed_parameters_json=proposed,
        deterministic_evidence_json=evidence,
        ai_notes=" ".join(notes),
        applied_at=applied_at,
    )
    db.add(suggestion)
    db.flush()
    return suggestion


def _formula_metrics(snapshot: dict[str, Any], snapshot_signal: dict[str, Any] | None) -> dict[str, Any] | None:
    if isinstance(snapshot_signal, dict):
        metrics = snapshot_signal.get("formula_metrics")
        if isinstance(metrics, dict):
            return metrics
    if isinstance(snapshot, dict):
        metrics = snapshot.get("formula_metrics")
        if isinstance(metrics, dict):
            return metrics
    return None


def _compute_fair_value(signal: dict[str, Any] | None, current_price: float) -> float:
    indicators = (signal or {}).get("indicators") or {}
    components: list[tuple[float, float]] = []
    for key, weight in (("sma_50", 0.35), ("SMA_50", 0.35), ("EMA_55", 0.35), ("bbands_middle", 0.30), ("BBM_20_2.0_2.0", 0.30)):
        value = _float(indicators.get(key))
        if value > 0:
            components.append((value, weight))
    if not components:
        return current_price
    total_weight = sum(weight for _, weight in components)
    return sum(value * weight for value, weight in components) / total_weight


def _suggestion_for_user(db: Session, current_user: User, suggestion_id: int) -> AgentFormulaSuggestion | None:
    return (
        db.query(AgentFormulaSuggestion)
        .filter(AgentFormulaSuggestion.id == suggestion_id, AgentFormulaSuggestion.user_id == current_user.id)
        .first()
    )


def _supersede_other_pending_suggestions(db: Session, current_user: User, keep_id: int | None) -> None:
    query = db.query(AgentFormulaSuggestion).filter(
        AgentFormulaSuggestion.user_id == current_user.id,
        AgentFormulaSuggestion.status == "pending",
    )
    if keep_id is not None:
        query = query.filter(AgentFormulaSuggestion.id != keep_id)
    query.update({"status": "superseded"}, synchronize_session=False)


def _normalise_scoring_weights(raw: Any) -> dict[str, dict[str, float]]:
    weights = deepcopy(DEFAULT_SCORING_WEIGHTS)
    if not isinstance(raw, Mapping):
        return weights
    for group, values in raw.items():
        if group not in weights or not isinstance(values, Mapping):
            continue
        for key, value in values.items():
            if key in weights[group]:
                weights[group][key] = _clamp_number(value, -1.0, 1.0)
    return weights


def _deep_merge(base: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    cursor: Any = data
    for part in path.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    cursor = data
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(cursor.get(part), dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _clamp_number(value: Any, min_value: float, max_value: float) -> float:
    numeric = _float(value, min_value)
    return min(max(numeric, min_value), max_value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
