from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.backtesting.engine import BacktestEngine
from app.backtesting.strategies import create_strategy
from app.config import settings
from app.models.backtest import BacktestRun, BacktestTrade
from app.models.instrument import Price
from app.models.research import AgentPrediction, AgentRecommendation, AgentRun, AssetDataStatus, ResearchSnapshot
from app.models.user import User
from app.services.asset_status import build_signal_status
from app.services.crew_execution import attempt_autonomous_execution, audit, get_or_create_guardrails
from app.services.crew_models import effective_model, invoke_ollama_json, mark_invocation_validation_failed, runtime_payload
from app.services.market_candles import load_candles_df
from app.services.market_resolution import configured_exchange_priority
from app.signals.engine import SignalEngine


AGENT_ROLES = [
    "Market Data Auditor",
    "Technical Analyst",
    "Risk Manager",
    "Backtest Analyst",
    "Portfolio Manager",
]


class PredictionPoint(BaseModel):
    minutes_ahead: int = Field(ge=1, le=10080)
    price: float = Field(gt=0)


class AgentDecision(BaseModel):
    action: Literal["buy", "sell", "hold", "reject"]
    confidence: float = Field(ge=0, le=1)
    thesis: str = Field(min_length=5, max_length=4000)
    risk_notes: str | None = Field(default=None, max_length=4000)
    strategy_name: str = "sma_cross"
    strategy_params: dict[str, Any] = Field(default_factory=lambda: {"short_window": 20, "long_window": 50})
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


@dataclass(frozen=True)
class CrewRunOptions:
    symbols: list[str]
    max_symbols: int
    auto_execute: bool
    paper_account_id: int | None


def runtime_status() -> dict[str, Any]:
    return runtime_payload()


def run_crew_cycle(db: Session, current_user: User, options: CrewRunOptions) -> AgentRun:
    profile = get_or_create_guardrails(db, current_user)
    research_model = effective_model(profile, "research")
    max_symbols = max(1, min(options.max_symbols or settings.CREW_MAX_SYMBOLS_PER_RUN, settings.CREW_MAX_SYMBOLS_PER_RUN))
    requested_symbols = [_normalize_symbol(symbol) for symbol in options.symbols if symbol.strip()]
    run = AgentRun(
        user_id=current_user.id,
        status="running",
        mode="supervised_auto",
        llm_provider=settings.CREW_LLM_PROVIDER,
        llm_base_url=settings.CREW_LLM_BASE_URL,
        llm_model=research_model,
        max_symbols=max_symbols,
        requested_symbols=requested_symbols,
        selected_symbols=[],
        summary={"agents": AGENT_ROLES},
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    audit(db, current_user, "crew_run_started", {"run_id": run.id, "requested_symbols": requested_symbols})

    status = runtime_status()
    if not status["enabled"] or not status["available"]:
        run.status = "failed"
        run.error_message = status["message"]
        run.completed_at = datetime.now(timezone.utc)
        run.summary = {"runtime": status, "agents": AGENT_ROLES}
        audit(db, current_user, "crew_run_failed", {"run_id": run.id, "reason": run.error_message})
        db.commit()
        db.refresh(run)
        return run

    assets = _select_ready_assets(db, requested_symbols, max_symbols)
    if not assets:
        run.status = "failed"
        run.error_message = "No ready, analyzable crypto assets were available for the requested crew run."
        run.completed_at = datetime.now(timezone.utc)
        run.summary = {"runtime": status, "agents": AGENT_ROLES, "selected": []}
        audit(db, current_user, "crew_run_failed", {"run_id": run.id, "reason": run.error_message})
        db.commit()
        db.refresh(run)
        return run

    client = OllamaCrewClient(model=research_model, db=db, current_user=current_user, run=run)
    selected_symbols: list[str] = []
    created_recommendations = 0
    executed_recommendations = 0
    rejected_recommendations = 0

    for asset in assets:
        snapshot = _build_snapshot(db, current_user, run, asset)
        if snapshot is None:
            continue
        selected_symbols.append(snapshot.symbol)
        try:
            decision = client.generate_decision(
                snapshot.snapshot,
                snapshot_id=snapshot.id,
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
            )
        except Exception as exc:
            audit(
                db,
                current_user,
                "agent_output_rejected",
                {"run_id": run.id, "snapshot_id": snapshot.id, "symbol": asset.symbol, "reason": str(exc)},
            )
            continue

        prediction = _store_prediction(db, current_user, run, snapshot, decision)
        recommendation = _store_recommendation(
            db=db,
            current_user=current_user,
            run=run,
            snapshot=snapshot,
            prediction=prediction,
            decision=decision,
            paper_account_id=options.paper_account_id,
            model_role="research",
            llm_model=research_model,
        )
        created_recommendations += 1

        if recommendation.action in {"buy", "sell"}:
            backtest_run, backtest_summary = _run_backtest_for_recommendation(db, current_user, recommendation, decision)
            if backtest_run is not None:
                recommendation.backtest_run_id = backtest_run.id
                recommendation.backtest_summary = backtest_summary
                recommendation.status = "proposed"
                recommendation.execution_reason = "Backtest completed; awaiting guardrail decision."
            else:
                recommendation.status = "rejected"
                recommendation.backtest_summary = backtest_summary
                recommendation.execution_reason = backtest_summary.get("reason", "Backtest did not complete.")
                recommendation.execution_decision = recommendation.execution_reason

            if options.auto_execute and recommendation.backtest_run_id:
                attempt_autonomous_execution(db, current_user, recommendation, decision.strategy_params)
        else:
            recommendation.status = "rejected"
            recommendation.execution_reason = f"Agent chose {recommendation.action}; no paper order was attempted."
            recommendation.execution_decision = recommendation.execution_reason

        if recommendation.status == "executed":
            executed_recommendations += 1
        elif recommendation.status == "rejected":
            rejected_recommendations += 1

    run.status = "completed"
    run.selected_symbols = selected_symbols
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {
        "runtime": status,
        "agents": AGENT_ROLES,
        "selected": selected_symbols,
        "recommendations": created_recommendations,
        "executed": executed_recommendations,
        "rejected": rejected_recommendations,
    }
    audit(db, current_user, "crew_run_completed", {"run_id": run.id, "summary": run.summary})
    db.commit()
    db.refresh(run)
    return run


class OllamaCrewClient:
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

    def generate_decision(
        self,
        snapshot: dict[str, Any],
        *,
        snapshot_id: int | None = None,
        exchange: str | None = None,
        symbol: str | None = None,
    ) -> AgentDecision:
        return self._generate_decision(snapshot, snapshot_id=snapshot_id, exchange=exchange, symbol=symbol)

    def _generate_decision(
        self,
        snapshot: dict[str, Any],
        *,
        snapshot_id: int | None,
        exchange: str | None,
        symbol: str | None,
    ) -> AgentDecision:
        prompt = _build_prompt(snapshot)
        if self.db is not None and self.current_user is not None:
            parsed, _, invocation = invoke_ollama_json(
                self.db,
                self.current_user,
                role="research",
                action_type="crew_decision",
                model=self.model,
                prompt=prompt,
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
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
                timeout=max(10, settings.CREW_LLM_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            raw = response.json().get("response")
            if not raw:
                raise ValueError("Ollama returned an empty response.")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("Agent response was not valid JSON.") from exc
            invocation = None
        try:
            return AgentDecision.model_validate(parsed)
        except ValidationError as exc:
            if invocation is not None and self.db is not None:
                mark_invocation_validation_failed(self.db, invocation, str(exc))
            raise ValueError(f"Agent response failed schema validation: {exc}") from exc


def _select_ready_assets(db: Session, requested_symbols: list[str], max_symbols: int) -> list[AssetDataStatus]:
    query = db.query(AssetDataStatus).filter(
        AssetDataStatus.status == "ready",
        AssetDataStatus.is_analyzable.is_(True),
        AssetDataStatus.row_count >= 50,
    )
    if requested_symbols:
        query = query.filter(AssetDataStatus.symbol.in_(requested_symbols))
    priority = configured_exchange_priority()
    rank = {exchange: idx for idx, exchange in enumerate(priority)}
    rows = query.all()
    rows.sort(
        key=lambda asset: (
            rank.get((asset.exchange or "").strip().lower(), 9999),
            -int(asset.row_count or 0),
            asset.symbol,
        )
    )

    selected: list[AssetDataStatus] = []
    seen_symbols: set[str] = set()
    for asset in rows:
        symbol_key = (asset.symbol or "").strip().upper()
        if symbol_key in seen_symbols:
            continue
        seen_symbols.add(symbol_key)
        selected.append(asset)
        if len(selected) >= max_symbols:
            break
    return selected


def _build_snapshot(
    db: Session,
    current_user: User,
    run: AgentRun,
    asset: AssetDataStatus,
) -> ResearchSnapshot | None:
    latest_ts = (
        db.query(func.max(Price.timestamp))
        .filter(Price.exchange == asset.exchange, Price.symbol == asset.symbol)
        .scalar()
    )
    latest_price = None
    if latest_ts is not None:
        latest_row = (
            db.query(Price)
            .filter(Price.exchange == asset.exchange, Price.symbol == asset.symbol, Price.timestamp == latest_ts)
            .first()
        )
        if latest_row and latest_row.close is not None:
            latest_price = float(latest_row.close)

    signal_payload = None
    try:
        signal = SignalEngine(db).generate_signal(
            asset.symbol,
            lookback=200,
            exchange=asset.exchange,
            include_externals=False,
        )
        signal_payload = signal.to_dict() if signal else None
    except Exception as exc:
        signal_payload = {"error": str(exc)}

    data_status = build_signal_status(
        exchange=asset.exchange,
        symbol=asset.symbol,
        row_count=int(asset.row_count or 0),
        latest_candle_at=latest_ts or asset.latest_candle_at,
        status_record=asset,
        has_signal=bool(signal_payload and "error" not in signal_payload),
    )
    if data_status["status"] != "ready":
        audit(db, current_user, "snapshot_skipped", {"run_id": run.id, "symbol": asset.symbol, "data_status": data_status})
        return None

    snapshot_payload = {
        "exchange": asset.exchange,
        "symbol": asset.symbol,
        "price": latest_price,
        "source_data_timestamp": latest_ts.isoformat() if latest_ts else None,
        "row_count": int(asset.row_count or 0),
        "data_status": data_status,
        "signal": signal_payload,
        "allowed_actions": ["buy", "sell", "hold", "reject"],
        "strategy_registry": ["sma_cross", "rsi", "buy_hold"],
        "agent_roles": AGENT_ROLES,
    }
    snapshot = ResearchSnapshot(
        user_id=current_user.id,
        run_id=run.id,
        exchange=asset.exchange,
        symbol=asset.symbol,
        price=latest_price,
        source_data_timestamp=latest_ts,
        row_count=int(asset.row_count or 0),
        data_status=data_status,
        signal=signal_payload,
        snapshot=snapshot_payload,
    )
    db.add(snapshot)
    db.flush()
    audit(db, current_user, "research_snapshot_created", {"run_id": run.id, "snapshot_id": snapshot.id, "symbol": asset.symbol})
    return snapshot


def _store_prediction(
    db: Session,
    current_user: User,
    run: AgentRun,
    snapshot: ResearchSnapshot,
    decision: AgentDecision,
) -> AgentPrediction:
    path = [point.model_dump() for point in decision.predicted_path]
    if not path and snapshot.price:
        multiplier = 1.0
        if decision.action == "buy":
            multiplier = 1.01
        elif decision.action == "sell":
            multiplier = 0.99
        path = [
            {"minutes_ahead": 60, "price": round(snapshot.price * ((1 + multiplier) / 2), 8)},
            {"minutes_ahead": decision.prediction_horizon_minutes, "price": round(snapshot.price * multiplier, 8)},
        ]
    prediction = AgentPrediction(
        user_id=current_user.id,
        run_id=run.id,
        snapshot_id=snapshot.id,
        exchange=snapshot.exchange,
        symbol=snapshot.symbol,
        horizon_minutes=decision.prediction_horizon_minutes,
        predicted_path=path,
        summary=decision.prediction_summary,
        confidence=decision.confidence,
    )
    db.add(prediction)
    db.flush()
    return prediction


def _store_recommendation(
    *,
    db: Session,
    current_user: User,
    run: AgentRun,
    snapshot: ResearchSnapshot,
    prediction: AgentPrediction,
    decision: AgentDecision,
    paper_account_id: int | None,
    model_role: str | None = None,
    llm_model: str | None = None,
) -> AgentRecommendation:
    recommendation = AgentRecommendation(
        user_id=current_user.id,
        run_id=run.id,
        snapshot_id=snapshot.id,
        prediction_id=prediction.id,
        agent_name="Portfolio Manager",
        strategy_name=decision.strategy_name.strip().lower(),
        exchange=snapshot.exchange,
        symbol=snapshot.symbol,
        action=decision.action,
        confidence=decision.confidence,
        thesis=decision.thesis,
        risk_notes=decision.risk_notes,
        source_data_timestamp=snapshot.source_data_timestamp,
        paper_account_id=paper_account_id,
        status="proposed",
        model_role=model_role,
        llm_model=llm_model,
        evidence_json={
            "snapshot_id": snapshot.id,
            "prediction_id": prediction.id,
            "agent_roles": AGENT_ROLES,
            "strategy_params": decision.strategy_params,
            "signal": snapshot.signal,
            "data_status": snapshot.data_status,
            "llm_model": llm_model,
            "model_role": model_role,
        },
    )
    db.add(recommendation)
    db.flush()
    audit(
        db,
        current_user,
        "recommendation_created",
        {"run_id": run.id, "snapshot_id": snapshot.id, "decision": decision.model_dump(mode="json")},
        recommendation_id=recommendation.id,
    )
    return recommendation


def _run_backtest_for_recommendation(
    db: Session,
    current_user: User,
    recommendation: AgentRecommendation,
    decision: AgentDecision,
) -> tuple[BacktestRun | None, dict[str, Any]]:
    latest_ts = (
        db.query(func.max(Price.timestamp))
        .filter(Price.exchange == recommendation.exchange, Price.symbol == recommendation.symbol)
        .scalar()
    )
    if latest_ts is None:
        return None, {"status": "failed", "reason": "No candle timestamp was available for backtest."}
    end = latest_ts if latest_ts.tzinfo else latest_ts.replace(tzinfo=timezone.utc)
    start = end - timedelta(days=7)
    try:
        candles = load_candles_df(
            db=db,
            exchange=recommendation.exchange,
            symbol=recommendation.symbol,
            start=start,
            end=end,
            timeframe="1m",
            source="auto",
        )
        if candles.df.empty or len(candles.df) < 50:
            return None, {"status": "failed", "reason": "Not enough candle data for required backtest.", "rows": len(candles.df)}
        strategy = create_strategy(decision.strategy_name, decision.strategy_params)
        result = BacktestEngine(
            initial_cash=10_000,
            fee_rate=0.001,
            slippage_bps=5.0,
            max_position_pct=0.10,
        ).run(candles.df, strategy)
    except Exception as exc:
        return None, {"status": "failed", "reason": str(exc)}

    run = BacktestRun(
        user_id=current_user.id,
        name=f"agent:{recommendation.strategy_name}:{recommendation.symbol}:{end.date().isoformat()}",
        symbol=recommendation.symbol,
        exchange=recommendation.exchange,
        timeframe="1m",
        start=start,
        end=end,
        initial_cash=10_000,
        fee_rate=0.001,
        slippage_bps=5.0,
        max_position_pct=0.10,
        strategy=strategy.name,
        strategy_params=decision.strategy_params or {},
        metrics=result.metrics,
        equity_curve=result.equity_curve[-500:],
    )
    db.add(run)
    db.flush()
    for trade in result.trades:
        db.add(
            BacktestTrade(
                run_id=run.id,
                timestamp=trade.timestamp,
                side=trade.side,
                price=trade.price,
                quantity=trade.quantity,
                fee=trade.fee,
                cash_balance=trade.cash_balance,
                equity=trade.equity,
                pnl=trade.pnl,
                reason=trade.reason,
            )
        )
    summary = {
        "status": "completed",
        "run_id": run.id,
        "metrics": result.metrics,
        "source": candles.source,
        "bucket_seconds": candles.bucket_seconds,
        "trades": len(result.trades),
    }
    audit(db, current_user, "backtest_completed", {"recommendation_id": recommendation.id, "summary": summary}, recommendation.id)
    return run, summary


def _build_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "You are a local crypto paper-trading crew. The team roles are Market Data Auditor, "
        "Technical Analyst, Risk Manager, Backtest Analyst, and Portfolio Manager. "
        "Return ONLY VALID JSON matching this schema exactly. DO NOT INCLUDE COMMENTS (like //) OR EXPLANATIONS INSIDE OR OUTSIDE THE JSON payload. "
        "{"
        '"action":"buy|sell|hold|reject",'
        '"confidence":0.0,'
        '"thesis":"short evidence-based thesis",'
        '"risk_notes":"main risks",'
        '"strategy_name":"sma_cross|rsi|buy_hold",'
        '"strategy_params":{},'
        '"prediction_summary":"short expected path",'
        '"prediction_horizon_minutes":240,'
        '"predicted_path":[{"minutes_ahead":60,"price":123.45}]'
        "}. Use reject if data quality is weak. Snapshot:\n"
        f"{json.dumps(snapshot, default=str)}"
    )


def _normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper().replace("/", "-")
    if not value:
        return value
    if "-" not in value:
        return f"{value}-USD"
    return value
