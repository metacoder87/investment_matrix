"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
    AlertTriangle,
    Bot,
    CirclePause,
    History,
    LineChart,
    Play,
    RefreshCcw,
    ShieldCheck,
    Terminal,
    Target,
    ToggleLeft,
    ToggleRight,
    Wallet,
} from "lucide-react";
import { getApiBaseUrl } from "@/utils/api";
import { cn } from "@/utils/cn";

interface RuntimeStatus {
    enabled: boolean;
    available: boolean;
    provider: string;
    model: string;
    status: string;
    message: string;
    model_routing?: ModelRoutingPayload;
}

type ModelRole = "default" | "research" | "thesis" | "risk" | "trade";

interface ModelRoutingPayload {
    selected: Record<ModelRole, string | null>;
    effective: Record<ModelRole, string>;
    fallback_model: string;
}

interface CrewModel {
    name: string;
    model: string;
    size: number | null;
    family: string | null;
    parameter_size: string | null;
    quantization_level: string | null;
    modified_at: string | null;
}

interface CrewModelsPayload {
    available: boolean;
    status: string;
    message: string;
    provider: string;
    base_url: string;
    models: CrewModel[];
    routing: ModelRoutingPayload;
    current_model: string;
}

interface ModelPerformance {
    model: string;
    role: string;
    calls: number;
    successes: number;
    failures: number;
    timeouts: number;
    approved: number;
    rejected: number;
    validation_failures: number;
    avg_latency_ms: number;
    theses_created: number;
    trades_approved: number;
    trades_rejected: number;
    success_rate_pct: number;
    timeout_rate_pct?: number;
    latest_status?: string | null;
    latest_error?: string | null;
    latest_validation_error?: string | null;
    last_used_at: string | null;
}

interface NoTradeDiagnostics {
    active_thesis_count: number;
    latest_run: {
        id: number;
        status: string;
        summary: Record<string, unknown>;
        created_at: string | null;
    } | null;
    latest_model_failure: {
        model: string;
        role: string;
        status: string;
        timeout_seconds: number | null;
        error_message: string | null;
        validation_error: string | null;
        created_at: string | null;
    } | null;
    blockers: string[];
    recommended_action: string;
}

interface CrewSettings {
    autonomous_enabled: boolean;
    research_enabled: boolean;
    trigger_monitor_enabled: boolean;
    bot_state?: string;
    primary_exchange?: string;
    global_crew_enabled?: boolean;
    global_research_enabled?: boolean;
    global_trigger_monitor_enabled?: boolean;
    research_interval_seconds: number;
    max_position_pct: number;
    max_daily_loss_pct: number;
    max_open_positions: number;
    max_trades_per_day: number;
    bankroll_reset_drawdown_pct: number;
    default_starting_bankroll: number;
    trade_cadence_mode?: string;
    ai_paper_account_id: number | null;
    model_routing?: Record<ModelRole, string | null>;
}

interface PortfolioSummary {
    account_id: number;
    account_name: string;
    cash_balance: number;
    available_bankroll: number;
    invested_value: number;
    total_equity: number;
    realized_pnl: number;
    unrealized_pnl: number;
    all_time_pnl: number;
    current_cycle_pnl: number;
    drawdown_pct: number;
    exposure_pct: number;
    open_positions: number;
    reset_count: number;
    last_reset_at: string | null;
    seconds_since_last_reset: number | null;
    settings: CrewSettings;
    positions: Position[];
    recent_orders: Order[];
}

interface EquityPoint {
    timestamp: string | null;
    cash_balance: number;
    invested_value: number;
    equity: number;
    drawdown_pct: number;
}

interface Thesis {
    id: number;
    symbol: string;
    exchange: string;
    strategy_name: string;
    confidence: number;
    thesis: string;
    risk_notes: string | null;
    entry_condition: string;
    entry_target: number | null;
    take_profit_target: number | null;
    stop_loss_target: number | null;
    latest_observed_price: number | null;
    status: string;
    expires_at: string | null;
    triggered_at: string | null;
    created_at: string | null;
    model_role?: string | null;
    llm_model?: string | null;
}

interface Position {
    id?: number;
    symbol: string;
    exchange: string;
    quantity: number;
    avg_entry_price: number;
    last_price: number;
    market_value: number;
    cost_basis: number;
    unrealized_pnl: number;
    return_pct: number;
}

interface Order {
    id: number;
    symbol: string;
    exchange: string;
    side: string;
    status: string;
    price: number;
    quantity: number;
    fee: number;
    strategy: string | null;
    reason: string | null;
    timestamp: string | null;
}

interface StrategyPerformance {
    strategy_name: string;
    recommendations: number;
    executed: number;
    blocked: number;
    wins: number;
    losses: number;
    avg_return_pct: number;
    success_rate_pct: number;
    last_used_at: string | null;
}

interface Lesson {
    id: number;
    symbol: string | null;
    strategy_name: string | null;
    outcome: string;
    return_pct: number | null;
    lesson: string;
    created_at: string | null;
}

interface ResetRecord {
    id: number;
    reset_number: number;
    starting_bankroll: number;
    equity_before_reset: number;
    drawdown_pct: number;
    realized_pnl: number;
    reason: string;
    lessons: string | null;
    created_at: string | null;
}

interface PaperAccount {
    id: number;
    name: string;
    cash_balance: number;
    equity: number;
}

interface AuditLog {
    id: number;
    event_type: string;
    recommendation_id: number | null;
    payload: Record<string, unknown>;
    created_at: string | null;
}

interface TraceEvent {
    id: number;
    run_id: number | null;
    recommendation_id: number | null;
    thesis_id: number | null;
    snapshot_id: number | null;
    role: string;
    exchange: string | null;
    symbol: string | null;
    event_type: string;
    status: string;
    public_summary: string;
    rationale: string | null;
    blocker_reason: string | null;
    evidence: Record<string, unknown>;
    validation_error: string | null;
    model_role: string | null;
    llm_model: string | null;
    prompt?: string | null;
    raw_model_json?: unknown;
    created_at: string | null;
}

const emptySummary: PortfolioSummary = {
    account_id: 0,
    account_name: "AI Team Bankroll",
    cash_balance: 0,
    available_bankroll: 0,
    invested_value: 0,
    total_equity: 0,
    realized_pnl: 0,
    unrealized_pnl: 0,
    all_time_pnl: 0,
    current_cycle_pnl: 0,
    drawdown_pct: 0,
    exposure_pct: 0,
    open_positions: 0,
    reset_count: 0,
    last_reset_at: null,
    seconds_since_last_reset: null,
    positions: [],
    recent_orders: [],
    settings: {
        autonomous_enabled: false,
        research_enabled: false,
        trigger_monitor_enabled: false,
        bot_state: "paused",
        primary_exchange: "kraken",
        global_crew_enabled: false,
        global_research_enabled: false,
        global_trigger_monitor_enabled: false,
        research_interval_seconds: 1800,
        max_position_pct: 0.35,
        max_daily_loss_pct: 0.1,
        max_open_positions: 12,
        max_trades_per_day: 40,
        bankroll_reset_drawdown_pct: 0.95,
        default_starting_bankroll: 10000,
        trade_cadence_mode: "aggressive_paper",
        ai_paper_account_id: null,
    },
};

const modelRoles: { role: ModelRole; label: string; note: string }[] = [
    { role: "default", label: "Global default", note: "Fallback for every unset role" },
    { role: "research", label: "Research", note: "General research and on-demand crew runs" },
    { role: "thesis", label: "Thesis / strategy", note: "Creates standing entry and exit plans" },
    { role: "risk", label: "Risk review", note: "Reserved for model-backed risk review" },
    { role: "trade", label: "Trade decision", note: "Approves or rejects crossed trigger trades" },
];

const emptyModelRouting: Record<ModelRole, string> = {
    default: "",
    research: "",
    thesis: "",
    risk: "",
    trade: "",
};

const emptyRoutingPayload: ModelRoutingPayload = {
    selected: { default: null, research: null, thesis: null, risk: null, trade: null },
    effective: { default: "", research: "", thesis: "", risk: "", trade: "" },
    fallback_model: "",
};

export default function CrewPage() {
    const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
    const [summary, setSummary] = useState<PortfolioSummary>(emptySummary);
    const [equity, setEquity] = useState<EquityPoint[]>([]);
    const [theses, setTheses] = useState<Thesis[]>([]);
    const [positions, setPositions] = useState<Position[]>([]);
    const [orders, setOrders] = useState<Order[]>([]);
    const [strategies, setStrategies] = useState<StrategyPerformance[]>([]);
    const [lessons, setLessons] = useState<Lesson[]>([]);
    const [resets, setResets] = useState<ResetRecord[]>([]);
    const [accounts, setAccounts] = useState<PaperAccount[]>([]);
    const [audit, setAudit] = useState<AuditLog[]>([]);
    const [activity, setActivity] = useState<TraceEvent[]>([]);
    const [models, setModels] = useState<CrewModelsPayload | null>(null);
    const [diagnostics, setDiagnostics] = useState<NoTradeDiagnostics | null>(null);
    const [modelRouting, setModelRouting] = useState<Record<ModelRole, string>>(emptyModelRouting);
    const [modelRoutingDirty, setModelRoutingDirty] = useState(false);
    const [modelPerformance, setModelPerformance] = useState<ModelPerformance[]>([]);
    const [modelTestStatus, setModelTestStatus] = useState<string | null>(null);
    const [degraded, setDegraded] = useState<string[]>([]);
    const [debugOpen, setDebugOpen] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const activeTheses = useMemo(() => theses.filter((item) => ["active", "entry_triggered"].includes(item.status)), [theses]);
    const currentStrategy = strategies[0]?.strategy_name || activeTheses[0]?.strategy_name || "No active strategy";
    const winRate = useMemo(() => {
        const wins = strategies.reduce((sum, item) => sum + item.wins, 0);
        const total = strategies.reduce((sum, item) => sum + item.wins + item.losses, 0);
        return total > 0 ? (wins / total) * 100 : 0;
    }, [strategies]);
    const executedTriggers = audit.filter((event) => event.event_type.includes("executed")).length;
    const blockedTriggers = audit.filter((event) => event.event_type.includes("blocked") || event.event_type.includes("rejected")).length;
    const primaryExchange = summary.settings.primary_exchange || "kraken";
    const botState = useMemo(() => {
        if (!runtime?.enabled || !runtime?.available) return "Setup needed";
        if (!summary.settings.global_research_enabled || !summary.settings.global_trigger_monitor_enabled) return "Setup needed";
        const rawState = summary.settings.bot_state || "paused";
        if (rawState === "running") return "Running";
        if (rawState === "researching") return "Researching";
        if (rawState === "monitoring") return "Monitoring";
        return "Paused";
    }, [
        runtime?.available,
        runtime?.enabled,
        summary.settings.bot_state,
        summary.settings.global_research_enabled,
        summary.settings.global_trigger_monitor_enabled,
    ]);
    const currentBlockers = useMemo(() => {
        const blockers: string[] = [];
        diagnostics?.blockers?.forEach((blocker) => {
            if (blocker && !blockers.includes(blocker)) blockers.push(blocker);
        });
        if (!runtime?.enabled || !runtime?.available) blockers.push(runtime?.message || "Ollama runtime is unavailable.");
        if (!summary.settings.global_research_enabled) blockers.push("Global research scheduler is disabled.");
        if (!summary.settings.global_trigger_monitor_enabled) blockers.push("Global trigger monitor is disabled.");
        if (!summary.settings.research_enabled) blockers.push("Research is paused for this user.");
        if (!summary.settings.trigger_monitor_enabled) blockers.push("Trigger monitoring is paused for this user.");
        if (!summary.settings.autonomous_enabled) blockers.push("Autonomous paper execution is paused.");
        if (activeTheses.length === 0) blockers.push("No active thesis is waiting on an entry target.");
        activity.slice(0, 8).forEach((event) => {
            if (event.blocker_reason && !blockers.includes(event.blocker_reason)) blockers.push(event.blocker_reason);
        });
        return blockers.slice(0, 8);
    }, [
        activeTheses.length,
        activity,
        diagnostics?.blockers,
        runtime?.available,
        runtime?.enabled,
        runtime?.message,
        summary.settings.autonomous_enabled,
        summary.settings.global_research_enabled,
        summary.settings.global_trigger_monitor_enabled,
        summary.settings.research_enabled,
        summary.settings.trigger_monitor_enabled,
    ]);

    const loadDashboard = useCallback(async () => {
        const base = getApiBaseUrl();
        const [
            runtimeRes,
            summaryRes,
            equityRes,
            positionsRes,
            ordersRes,
            strategiesRes,
            thesesRes,
            resetsRes,
            lessonsRes,
            accountsRes,
            auditRes,
            activityRes,
            modelsRes,
            modelPerformanceRes,
            diagnosticsRes,
        ] = await Promise.all([
            fetchJson(`${base}/crew/runtime`),
            fetchJson(`${base}/crew/portfolio/summary`),
            fetchJson(`${base}/crew/portfolio/equity`),
            fetchJson(`${base}/crew/portfolio/positions`),
            fetchJson(`${base}/crew/portfolio/orders`),
            fetchJson(`${base}/crew/strategies/performance`),
            fetchJson(`${base}/crew/theses`),
            fetchJson(`${base}/crew/resets`),
            fetchJson(`${base}/crew/lessons`),
            fetchJson(`${base}/paper/accounts`),
            fetchJson(`${base}/crew/audit`),
            fetchJson(`${base}/crew/activity?limit=200&debug=${debugOpen ? "true" : "false"}`),
            fetchJson(`${base}/crew/models`),
            fetchJson(`${base}/crew/model-performance`),
            fetchJson(`${base}/crew/no-trade-diagnostics`),
        ]);

        if (!summaryRes.ok) {
            throw new Error("Sign in to view the AI trading team.");
        }

        const degradedMessages = [
            runtimeRes,
            equityRes,
            positionsRes,
            ordersRes,
            strategiesRes,
            thesesRes,
            resetsRes,
            lessonsRes,
            accountsRes,
            auditRes,
            activityRes,
            modelsRes,
            modelPerformanceRes,
            diagnosticsRes,
        ].filter((item) => !item.ok).map((item) => item.error);
        setDegraded(degradedMessages);

        const summaryPayload = normalizeSummary(summaryRes.value);
        setRuntime(normalizeRuntime(runtimeRes.value));
        setSummary(summaryPayload);
        setEquity(asArray<EquityPoint>(equityRes.value));
        setPositions(asArray<Position>(positionsRes.value, summaryPayload.positions));
        setOrders(asArray<Order>(ordersRes.value, summaryPayload.recent_orders));
        setStrategies(asArray<StrategyPerformance>(strategiesRes.value));
        setTheses(asArray<Thesis>(thesesRes.value));
        setResets(asArray<ResetRecord>(resetsRes.value));
        setLessons(asArray<Lesson>(lessonsRes.value));
        setAccounts(asArray<PaperAccount>(accountsRes.value));
        setAudit(asArray<AuditLog>(auditRes.value));
        setActivity(asArray<TraceEvent>(activityRes.value));
        setDiagnostics(normalizeDiagnostics(diagnosticsRes.value));
        if (modelsRes.ok) {
            const modelsPayload = normalizeModels(modelsRes.value);
            setModels(modelsPayload);
            if (!modelRoutingDirty) {
                setModelRouting({
                    ...emptyModelRouting,
                    ...(Object.fromEntries(
                        modelRoles.map(({ role }) => [role, modelsPayload.routing?.selected?.[role] || ""]),
                    ) as Record<ModelRole, string>),
                });
            }
        }
        setModelPerformance(asArray<ModelPerformance>(modelPerformanceRes.value).map(normalizeModelPerformance));
        setError(null);
    }, [debugOpen, modelRoutingDirty]);

    useEffect(() => {
        loadDashboard().catch((err) => setError(err instanceof Error ? err.message : "AI team dashboard unavailable."));
        const timer = window.setInterval(() => {
            loadDashboard().catch(() => undefined);
        }, 15000);
        return () => window.clearInterval(timer);
    }, [loadDashboard]);

    const patchAutonomy = async (changes: Partial<CrewSettings>) => {
        setLoading(true);
        setError(null);
        setNotice(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/autonomy`, {
                method: "PATCH",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(changes),
            });
            if (!response.ok) throw new Error("Unable to update AI autonomy settings.");
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to update AI autonomy settings.");
        } finally {
            setLoading(false);
        }
    };

    const startBot = async () => {
        setLoading(true);
        setError(null);
        setNotice(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/autonomy/start`, {
                method: "POST",
                credentials: "include",
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, "Unable to start AI bot."));
            const payload = await response.json();
            setNotice(`AI bot started on ${(payload.primary_exchange || primaryExchange).toUpperCase()}. Immediate research task queued.`);
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to start AI bot.");
        } finally {
            setLoading(false);
        }
    };

    const pauseBot = async () => {
        setLoading(true);
        setError(null);
        setNotice(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/autonomy/pause`, {
                method: "POST",
                credentials: "include",
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, "Unable to pause AI bot."));
            setNotice("AI bot paused. Research, trigger monitoring, and autonomous paper execution are disabled for this user.");
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to pause AI bot.");
        } finally {
            setLoading(false);
        }
    };

    const saveTestAndRunModels = async () => {
        setLoading(true);
        setError(null);
        setNotice(null);
        setModelTestStatus("Saving model routing...");
        try {
            const base = getApiBaseUrl();
            const saveResponse = await fetch(`${base}/crew/model-routing`, {
                method: "PATCH",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(modelRouting),
            });
            if (!saveResponse.ok) throw new Error(await responseErrorMessage(saveResponse, "Unable to save model routing."));
            const saved = await saveResponse.json();
            setModelRoutingDirty(false);
            const effective = saved.routing?.effective || models?.routing?.effective || {};
            const rolesToTest: ModelRole[] = ["thesis", "trade"];
            for (const role of rolesToTest) {
                const model = modelRouting[role] || effective[role] || modelRouting.default || effective.default;
                if (!model) continue;
                setModelTestStatus(`Testing ${role} model: ${model}`);
                const testResponse = await fetch(`${base}/crew/model/test`, {
                    method: "POST",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ role, model }),
                });
                if (!testResponse.ok) throw new Error(await responseErrorMessage(testResponse, `Unable to test ${model}.`));
                const result = await testResponse.json();
                if (!result.ok) throw new Error(result.message || `${model} failed the ${role} probe.`);
            }
            setModelTestStatus("Model probes passed. Queueing research...");
            const runResponse = await fetch(`${base}/crew/research/run-now`, {
                method: "POST",
                credentials: "include",
            });
            if (!runResponse.ok) throw new Error(await responseErrorMessage(runResponse, "Models saved and tested, but research could not be queued."));
            setNotice("Model routing saved, thesis/trade probes passed, and immediate research was queued.");
            setModelTestStatus(null);
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to save, test, and run model routing.");
        } finally {
            setLoading(false);
        }
    };

    const testSingleModel = async (role: ModelRole) => {
        const model = modelRouting[role] || models?.routing?.effective?.[role] || modelRouting.default || models?.routing?.effective?.default;
        if (!model) {
            setError("Choose a model before running a probe.");
            return;
        }
        setLoading(true);
        setError(null);
        setNotice(null);
        setModelTestStatus(`Testing ${role} model: ${model}`);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/model/test`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ role, model }),
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, `Unable to test ${model}.`));
            const result = await response.json();
            if (!result.ok) throw new Error(result.message || `${model} failed the probe.`);
            setNotice(`${model} passed the ${role} probe in ${result.latency_ms ?? "unknown"} ms.`);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Model probe failed.");
        } finally {
            setModelTestStatus(null);
            setLoading(false);
        }
    };

    const useFastPaperDefaults = () => {
        const selected = chooseFastModel(models?.models || []);
        if (!selected) {
            setError("No downloaded non-vision Ollama model is available for fast paper-trading defaults.");
            return;
        }
        setModelRouting({
            default: selected,
            research: selected,
            thesis: selected,
            risk: "",
            trade: selected,
        });
        setModelRoutingDirty(true);
        setNotice(`${selected} selected for default, research, thesis, and trade decision roles. Save and test before running research.`);
    };

    const runThesisDryRun = async () => {
        setLoading(true);
        setError(null);
        setNotice(null);
        setModelTestStatus("Running one-symbol thesis dry-run...");
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/research/dry-run`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, "Unable to run thesis dry-run."));
            const result = await response.json();
            if (!result.ok) {
                throw new Error(result.message || "The selected thesis model could not produce a valid dry-run thesis.");
            }
            setNotice(`${result.model} produced a valid ${result.exchange?.toUpperCase()}:${result.symbol} thesis dry-run.`);
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to run thesis dry-run.");
            await loadDashboard();
        } finally {
            setModelTestStatus(null);
            setLoading(false);
        }
    };

    const backfillPrimaryExchange = async () => {
        setLoading(true);
        setError(null);
        setNotice(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/backfill/universe?exchange=${encodeURIComponent(primaryExchange)}`, {
                method: "POST",
                credentials: "include",
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, `Unable to backfill ${primaryExchange.toUpperCase()} assets.`));
            setNotice(`${primaryExchange.toUpperCase()} universe backfill queued. The bot can start after enough candles are ready.`);
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : `Unable to backfill ${primaryExchange.toUpperCase()} assets.`);
        } finally {
            setLoading(false);
        }
    };

    const manualReset = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/resets`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    reason: "Manual reset from AI team dashboard.",
                    lessons: "Manual reset requested; restart with clean bankroll and preserve prior trade history for review.",
                }),
            });
            if (!response.ok) throw new Error("Unable to reset AI bankroll.");
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to reset AI bankroll.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="mx-auto max-w-7xl space-y-6 p-4 md:p-8">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-white">AI Trading Team</h1>
                    <p className="mt-1 max-w-3xl text-sm text-gray-400">
                        Autonomous paper research, target monitoring, bankroll control, strategy performance, and audit history.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <button
                        onClick={() => loadDashboard()}
                        className="inline-flex items-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-200 hover:bg-white/10"
                    >
                        <RefreshCcw className="h-4 w-4" />
                        Refresh
                    </button>
                    <button
                        onClick={startBot}
                        disabled={loading || botState === "Running"}
                        className="inline-flex items-center gap-2 rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50"
                    >
                        <Play className="h-4 w-4" />
                        Start Bot
                    </button>
                    <button
                        onClick={pauseBot}
                        disabled={loading}
                        className="inline-flex items-center gap-2 rounded border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-sm font-medium text-yellow-100 hover:bg-yellow-500/20 disabled:opacity-50"
                    >
                        <CirclePause className="h-4 w-4" />
                        Pause Bot
                    </button>
                </div>
            </div>

            {error ? (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">{error}</div>
            ) : null}
            {notice ? (
                <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-4 text-sm text-cyan-100">{notice}</div>
            ) : null}
            {degraded.length ? (
                <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-4 text-sm text-yellow-100">
                    Crew dashboard loaded with partial data: {degraded.slice(0, 3).join(" ")}
                </div>
            ) : null}

            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <Metric icon={Wallet} label="Available bankroll" value={formatCurrency(summary.available_bankroll)} />
                <Metric icon={LineChart} label="Total equity" value={formatCurrency(summary.total_equity)} delta={summary.current_cycle_pnl} />
                <Metric icon={Target} label="Amount invested" value={formatCurrency(summary.invested_value)} />
                <Metric icon={AlertTriangle} label="Drawdown" value={`${summary.drawdown_pct.toFixed(2)}%`} />
                <Metric icon={ShieldCheck} label="All-time PnL" value={formatCurrency(summary.all_time_pnl)} delta={summary.all_time_pnl} />
                <Metric icon={Bot} label="AI win rate" value={`${winRate.toFixed(1)}%`} />
                <Metric icon={History} label="Bankroll resets" value={summary.reset_count} />
                <Metric icon={CirclePause} label="Since reset" value={formatDuration(summary.seconds_since_last_reset)} />
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
                <Panel title="Bankroll Curve">
                    <div className="p-5">
                        <DualLineChart
                            points={equity.length ? equity : [{
                                timestamp: new Date().toISOString(),
                                cash_balance: summary.cash_balance,
                                invested_value: summary.invested_value,
                                equity: summary.total_equity,
                                drawdown_pct: summary.drawdown_pct,
                            }]}
                        />
                    </div>
                </Panel>

                <Panel title="Autonomy">
                    <div className="space-y-4 p-5">
                        <div className="rounded border border-white/10 bg-black/30 p-3">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <div className="text-sm font-medium text-white">Bot state</div>
                                    <div className="text-xs text-gray-500">Primary source and paper venue: {primaryExchange.toUpperCase()}</div>
                                </div>
                                <StatusPill status={botState.toLowerCase().replace(" ", "_")} />
                            </div>
                            <button
                                onClick={backfillPrimaryExchange}
                                disabled={loading}
                                className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-200 hover:bg-white/10 disabled:opacity-50"
                            >
                                <RefreshCcw className="h-4 w-4" />
                                Backfill {primaryExchange.toUpperCase()} assets
                            </button>
                        </div>
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <div className="text-sm font-medium text-white">Paper trading</div>
                                <div className="text-xs text-gray-500">Execution after trigger and guardrail approval</div>
                            </div>
                            <Toggle
                                enabled={summary.settings.autonomous_enabled}
                                onClick={() => patchAutonomy({ autonomous_enabled: !summary.settings.autonomous_enabled })}
                            />
                        </div>
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <div className="text-sm font-medium text-white">Research loop</div>
                                <div className="text-xs text-gray-500">Every {Math.round(summary.settings.research_interval_seconds / 60)} minutes</div>
                            </div>
                            <Toggle
                                enabled={summary.settings.research_enabled}
                                onClick={() => patchAutonomy({ research_enabled: !summary.settings.research_enabled })}
                            />
                        </div>
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <div className="text-sm font-medium text-white">Trigger monitor</div>
                                <div className="text-xs text-gray-500">Entry, take-profit, and stop-loss targets</div>
                            </div>
                            <Toggle
                                enabled={summary.settings.trigger_monitor_enabled}
                                onClick={() => patchAutonomy({ trigger_monitor_enabled: !summary.settings.trigger_monitor_enabled })}
                            />
                        </div>
                        <div className="grid grid-cols-2 gap-3 text-sm">
                            <Info label="Max position" value={`${(summary.settings.max_position_pct * 100).toFixed(0)}%`} />
                            <Info label="Open positions" value={`${summary.open_positions}/${summary.settings.max_open_positions}`} />
                            <Info label="Daily loss cap" value={`${(summary.settings.max_daily_loss_pct * 100).toFixed(0)}%`} />
                            <Info label="Trades/day" value={summary.settings.max_trades_per_day} />
                            <Info label="Reset threshold" value={`${(summary.settings.bankroll_reset_drawdown_pct * 100).toFixed(0)}%`} />
                            <Info label="Starting bankroll" value={formatCurrency(summary.settings.default_starting_bankroll)} />
                        </div>
                        <select
                            value={summary.settings.ai_paper_account_id || summary.account_id || ""}
                            onChange={(event) => patchAutonomy({ ai_paper_account_id: Number(event.target.value) })}
                            className="w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400"
                            aria-label="AI paper account"
                        >
                            {accounts.map((account) => (
                                <option key={account.id} value={account.id}>{account.name}</option>
                            ))}
                        </select>
                        <button
                            onClick={manualReset}
                            disabled={loading}
                            className="inline-flex w-full items-center justify-center gap-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-100 hover:bg-red-500/20 disabled:opacity-50"
                        >
                            <RefreshCcw className="h-4 w-4" />
                            Reset bankroll
                        </button>
                        <div className="rounded border border-white/10 bg-black/30 p-3 text-xs text-gray-400">
                            {runtime?.message || "Crew runtime has not reported status yet."}
                        </div>
                    </div>
                </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
                <Panel title="Crew Models">
                    <div className="space-y-4 p-5">
                        <div className="rounded border border-white/10 bg-black/30 p-3 text-sm">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <div className="font-medium text-white">Ollama model routing</div>
                                    <div className="text-xs text-gray-500">
                                        {models?.message || runtime?.message || "Loading local models..."}
                                    </div>
                                </div>
                                <StatusPill status={models?.status || runtime?.status || "checking"} />
                            </div>
                        </div>
                        <div className="grid gap-3">
                            {modelRoles.map(({ role, label, note }) => (
                                <div key={role} className="grid gap-2 rounded border border-white/10 bg-black/20 p-3 md:grid-cols-[0.75fr_1fr_auto] md:items-center">
                                    <div>
                                        <div className="text-sm font-medium text-white">{label}</div>
                                        <div className="text-xs text-gray-500">{note}</div>
                                    </div>
                                    <select
                                        value={modelRouting[role] || ""}
                                        onChange={(event) => {
                                            setModelRoutingDirty(true);
                                            setModelRouting((current) => ({ ...current, [role]: event.target.value }));
                                        }}
                                        className="w-full rounded border border-white/10 bg-black/50 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400"
                                        aria-label={`${label} model`}
                                    >
                                        <option value="">
                                            Use default ({models?.routing?.effective?.[role] || runtime?.model || "configured model"})
                                        </option>
                                        {(models?.models || []).map((model) => (
                                            <option key={`${role}:${model.name}`} value={model.name}>
                                                {model.name}
                                            </option>
                                        ))}
                                    </select>
                                    <button
                                        onClick={() => testSingleModel(role)}
                                        disabled={loading || !(modelRouting[role] || models?.routing?.effective?.[role])}
                                        className="inline-flex items-center justify-center rounded border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-200 hover:bg-white/10 disabled:opacity-50"
                                    >
                                        Test
                                    </button>
                                </div>
                            ))}
                        </div>
                        {modelTestStatus ? <div className="rounded border border-cyan-500/20 bg-cyan-500/10 p-3 text-sm text-cyan-100">{modelTestStatus}</div> : null}
                        <div className="grid gap-2 sm:grid-cols-2">
                            <button
                                onClick={useFastPaperDefaults}
                                disabled={loading || !models?.models?.length}
                                className="inline-flex w-full items-center justify-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-gray-100 hover:bg-white/10 disabled:opacity-50"
                            >
                                <Bot className="h-4 w-4" />
                                Use fast paper-trading defaults
                            </button>
                            <button
                                onClick={runThesisDryRun}
                                disabled={loading}
                                className="inline-flex w-full items-center justify-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-gray-100 hover:bg-white/10 disabled:opacity-50"
                            >
                                <Target className="h-4 w-4" />
                                Run thesis dry-run
                            </button>
                        </div>
                        <button
                            onClick={saveTestAndRunModels}
                            disabled={loading || !models?.models?.length}
                            className="inline-flex w-full items-center justify-center gap-2 rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50"
                        >
                            <Bot className="h-4 w-4" />
                            Save, test thesis/trade models, run research
                        </button>
                    </div>
                </Panel>

                <Panel title="Downloaded Models">
                    <div className="max-h-[520px] divide-y divide-white/5 overflow-y-auto">
                        {!models?.models?.length ? (
                            <Empty text="No downloaded Ollama models were returned. Check that Ollama is reachable from the backend." />
                        ) : models.models.map((model) => (
                            <div key={model.name} className="px-5 py-4">
                                <div className="font-mono text-sm text-white">{model.name}</div>
                                <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-500">
                                    <span>{formatBytes(model.size)}</span>
                                    {model.parameter_size ? <span>{model.parameter_size}</span> : null}
                                    {model.quantization_level ? <span>{model.quantization_level}</span> : null}
                                    {model.family ? <span>{model.family}</span> : null}
                                </div>
                            </div>
                        ))}
                    </div>
                </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
                <Panel title="Why No Trade Yet?">
                    <div className="space-y-3 p-5">
                        <div className="flex flex-wrap items-center gap-2">
                            <StatusPill status={botState.toLowerCase().replace(" ", "_")} />
                            <StatusPill status={summary.settings.trade_cadence_mode || "aggressive_paper"} />
                            <span className="text-xs text-gray-500">{activeTheses.length} active theses</span>
                        </div>
                        {currentBlockers.length === 0 ? (
                            <div className="rounded border border-green-500/20 bg-green-500/10 p-3 text-sm text-green-100">
                                No current blocker found. The monitor is waiting for target prices or the next scheduler tick.
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {currentBlockers.map((blocker) => (
                                    <div key={blocker} className="rounded border border-yellow-500/20 bg-yellow-500/10 p-3 text-sm text-yellow-100">
                                        {blocker}
                                    </div>
                                ))}
                            </div>
                        )}
                        {diagnostics?.recommended_action ? (
                            <div className="rounded border border-cyan-500/20 bg-cyan-500/10 p-3 text-sm text-cyan-100">
                                {diagnostics.recommended_action}
                            </div>
                        ) : null}
                        {diagnostics?.latest_model_failure ? (
                            <div className="rounded border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-100">
                                Latest model issue: {diagnostics.latest_model_failure.role} / {diagnostics.latest_model_failure.model} / {diagnostics.latest_model_failure.status}
                            </div>
                        ) : null}
                    </div>
                </Panel>

                <Panel title="Decision Log">
                    <div className="p-5">
                        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs text-gray-500">Structured rationale, evidence, and blockers from the local AI team.</div>
                            <button
                                onClick={() => setDebugOpen((value) => !value)}
                                className="inline-flex items-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-200 hover:bg-white/10"
                            >
                                <Terminal className="h-4 w-4" />
                                {debugOpen ? "Hide debug JSON" : "Show debug JSON"}
                            </button>
                        </div>
                        <div className="max-h-[520px] space-y-3 overflow-y-auto pr-1">
                            {activity.length === 0 ? (
                                <Empty text="No AI activity recorded yet. Start the bot or wait for the next scheduled research cycle." />
                            ) : activity.map((event) => (
                                <TraceRow key={event.id} event={event} debugOpen={debugOpen} />
                            ))}
                        </div>
                    </div>
                </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                <Panel title="Current Strategy">
                    <div className="space-y-4 p-5">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <div className="text-2xl font-semibold text-white">{currentStrategy}</div>
                                <div className="mt-1 text-sm text-gray-500">{activeTheses.length} active target conditions</div>
                            </div>
                            <StatusPill status={runtime?.available ? "runtime_ready" : runtime?.status || "runtime_disabled"} />
                        </div>
                        <div className="grid gap-3 sm:grid-cols-3">
                            <Info label="Executed triggers" value={executedTriggers} />
                            <Info label="Blocked triggers" value={blockedTriggers} />
                            <Info label="Exposure" value={`${summary.exposure_pct.toFixed(1)}%`} />
                        </div>
                    </div>
                </Panel>

                <Panel title="Strategy Performance">
                    <div className="divide-y divide-white/5">
                        {strategies.length === 0 ? (
                            <Empty text="No completed strategy history yet." />
                        ) : strategies.slice(0, 6).map((strategy) => (
                            <div key={strategy.strategy_name} className="grid gap-3 px-5 py-4 md:grid-cols-[1fr_0.7fr_0.7fr_0.7fr] md:items-center">
                                <div>
                                    <div className="font-medium text-white">{strategy.strategy_name}</div>
                                    <div className="text-xs text-gray-500">{strategy.recommendations} recommendations / {strategy.executed} executed</div>
                                </div>
                                <Info label="Success" value={`${strategy.success_rate_pct.toFixed(1)}%`} />
                                <Info label="Avg return" value={`${strategy.avg_return_pct.toFixed(2)}%`} />
                                <Info label="W/L" value={`${strategy.wins}/${strategy.losses}`} />
                            </div>
                        ))}
                    </div>
                </Panel>
            </section>

            <Panel title="Model Performance">
                <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-white/10 text-sm">
                        <thead className="bg-white/[0.03] text-xs uppercase text-gray-500">
                            <tr>
                                <th className="px-4 py-3 text-left font-medium">Model</th>
                                <th className="px-4 py-3 text-left font-medium">Role</th>
                                <th className="px-4 py-3 text-right font-medium">Calls</th>
                                <th className="px-4 py-3 text-right font-medium">Success</th>
                                <th className="px-4 py-3 text-right font-medium">Timeouts</th>
                                <th className="px-4 py-3 text-right font-medium">Latency</th>
                                <th className="px-4 py-3 text-right font-medium">Theses</th>
                                <th className="px-4 py-3 text-right font-medium">Trade A/R</th>
                                <th className="px-4 py-3 text-right font-medium">Last used</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                            {modelPerformance.length === 0 ? (
                                <tr>
                                    <td colSpan={9}>
                                        <Empty text="No model calls have been recorded yet." />
                                    </td>
                                </tr>
                            ) : modelPerformance.map((row) => (
                                <tr key={`${row.role}:${row.model}`} className="text-gray-300">
                                    <td className="max-w-[360px] truncate px-4 py-3 font-mono text-xs text-white">{row.model}</td>
                                    <td className="px-4 py-3">
                                        <div>{row.role}</div>
                                        {row.latest_status ? <div className="text-xs text-gray-500">Latest: {row.latest_status}</div> : null}
                                        {row.latest_error || row.latest_validation_error ? (
                                            <div className="max-w-[280px] truncate text-xs text-red-200">
                                                {row.latest_error || row.latest_validation_error}
                                            </div>
                                        ) : null}
                                    </td>
                                    <td className="px-4 py-3 text-right font-mono">{row.calls}</td>
                                    <td className="px-4 py-3 text-right font-mono">{row.success_rate_pct.toFixed(1)}%</td>
                                    <td className="px-4 py-3 text-right font-mono">
                                        {row.timeouts}
                                        {row.timeout_rate_pct ? <div className="text-xs text-gray-500">{row.timeout_rate_pct.toFixed(1)}%</div> : null}
                                    </td>
                                    <td className="px-4 py-3 text-right font-mono">{row.avg_latency_ms ? `${row.avg_latency_ms}ms` : "--"}</td>
                                    <td className="px-4 py-3 text-right font-mono">{row.theses_created}</td>
                                    <td className="px-4 py-3 text-right font-mono">{row.trades_approved}/{row.trades_rejected}</td>
                                    <td className="px-4 py-3 text-right text-xs text-gray-500">{formatDate(row.last_used_at)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </Panel>

            <Panel title="Active Target Conditions">
                <div className="grid gap-3 p-4 lg:grid-cols-2">
                    {activeTheses.length === 0 ? (
                        <Empty text="No active theses. Enable research after configuring Ollama to let the team create standing targets." />
                    ) : activeTheses.map((thesis) => (
                        <div key={thesis.id} className="rounded border border-white/10 bg-black/30 p-4">
                            <div className="mb-3 flex items-start justify-between gap-3">
                                <div>
                                    <div className="text-lg font-semibold text-white">{thesis.symbol}</div>
                                    <div className="text-xs text-gray-500">
                                        {thesis.exchange.toUpperCase()} / {thesis.strategy_name}
                                        {thesis.llm_model ? ` / ${thesis.llm_model}` : ""}
                                    </div>
                                </div>
                                <StatusPill status={thesis.status} />
                            </div>
                            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                                <Info label="Latest" value={formatPrice(thesis.latest_observed_price)} />
                                <Info label="Entry" value={formatPrice(thesis.entry_target)} />
                                <Info label="Take profit" value={formatPrice(thesis.take_profit_target)} />
                                <Info label="Stop loss" value={formatPrice(thesis.stop_loss_target)} />
                            </div>
                            <div className="mt-3 h-2 overflow-hidden rounded bg-white/10">
                                <div className="h-full bg-cyan-400" style={{ width: `${Math.round(thesis.confidence * 100)}%` }} />
                            </div>
                            <p className="mt-3 line-clamp-2 text-sm text-gray-300">{thesis.thesis}</p>
                            <div className="mt-3 text-xs text-gray-500">Expires {formatDate(thesis.expires_at)}</div>
                        </div>
                    ))}
                </div>
            </Panel>

            <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                <Panel title="Owned Assets">
                    <div className="divide-y divide-white/5">
                        {positions.length === 0 ? (
                            <Empty text="The AI team does not currently own any paper assets." />
                        ) : positions.map((position) => (
                            <div key={`${position.exchange}:${position.symbol}`} className="grid gap-3 px-5 py-4 md:grid-cols-[1fr_0.8fr_0.8fr_0.8fr] md:items-center">
                                <div>
                                    <div className="font-medium text-white">{position.symbol}</div>
                                    <div className="text-xs text-gray-500">{position.quantity.toFixed(6)} units</div>
                                </div>
                                <Info label="Market value" value={formatCurrency(position.market_value)} />
                                <Info label="Unrealized" value={formatCurrency(position.unrealized_pnl)} />
                                <Info label="Return" value={`${position.return_pct.toFixed(2)}%`} />
                            </div>
                        ))}
                    </div>
                </Panel>

                <Panel title="Bought And Sold">
                    <div className="max-h-[520px] divide-y divide-white/5 overflow-y-auto">
                        {orders.length === 0 ? (
                            <Empty text="No AI paper trades have executed yet." />
                        ) : orders.map((order) => (
                            <div key={order.id} className="grid gap-3 px-5 py-4 md:grid-cols-[0.5fr_1fr_0.8fr_0.8fr] md:items-center">
                                <StatusPill status={order.side} />
                                <div>
                                    <div className="font-medium text-white">{order.symbol}</div>
                                    <div className="text-xs text-gray-500">{order.strategy || "strategy"} / {order.reason || "paper"}</div>
                                </div>
                                <Info label="Price" value={formatPrice(order.price)} />
                                <Info label="When" value={formatDate(order.timestamp)} />
                            </div>
                        ))}
                    </div>
                </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                <Panel title="Learning Memory">
                    <div className="max-h-[460px] divide-y divide-white/5 overflow-y-auto">
                        {lessons.length === 0 ? (
                            <Empty text="Lessons will appear after wins, losses, blocked triggers, and resets." />
                        ) : lessons.map((lesson) => (
                            <div key={lesson.id} className="px-5 py-4">
                                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                                    <div className="text-sm font-medium text-white">
                                        {[lesson.symbol, lesson.strategy_name, lesson.outcome.replaceAll("_", " ")].filter(Boolean).join(" / ")}
                                    </div>
                                    <div className="text-xs text-gray-500">{formatDate(lesson.created_at)}</div>
                                </div>
                                <p className="text-sm text-gray-300">{lesson.lesson}</p>
                                {lesson.return_pct !== null && (
                                    <div className="mt-2 text-xs text-gray-500">Return {lesson.return_pct.toFixed(2)}%</div>
                                )}
                            </div>
                        ))}
                    </div>
                </Panel>

                <Panel title="Reset History">
                    <div className="max-h-[460px] divide-y divide-white/5 overflow-y-auto">
                        {resets.length === 0 ? (
                            <Empty text="No bankroll resets recorded." />
                        ) : resets.map((reset) => (
                            <div key={reset.id} className="px-5 py-4">
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                                    <div className="font-medium text-white">Reset #{reset.reset_number}</div>
                                    <div className="text-xs text-gray-500">{formatDate(reset.created_at)}</div>
                                </div>
                                <div className="grid grid-cols-2 gap-3 text-sm">
                                    <Info label="Equity before" value={formatCurrency(reset.equity_before_reset)} />
                                    <Info label="Drawdown" value={`${reset.drawdown_pct.toFixed(2)}%`} />
                                    <Info label="Starting bankroll" value={formatCurrency(reset.starting_bankroll)} />
                                    <Info label="P/L" value={formatCurrency(reset.realized_pnl)} />
                                </div>
                                <p className="mt-3 text-sm text-gray-300">{reset.lessons || reset.reason}</p>
                            </div>
                        ))}
                    </div>
                </Panel>
            </section>
        </main>
    );
}

async function responseErrorMessage(response: Response, fallback: string) {
    try {
        const body = await response.json();
        if (typeof body?.detail === "string") return body.detail;
        if (typeof body?.detail?.message === "string") return body.detail.message;
        if (typeof body?.message === "string") return body.message;
    } catch {
        return fallback;
    }
    return fallback;
}

async function fetchJson(url: string): Promise<{ ok: boolean; value: unknown; error: string }> {
    try {
        const response = await fetch(url, { credentials: "include" });
        if (!response.ok) {
            return { ok: false, value: null, error: `${url.split("/api/").pop() || url} returned ${response.status}` };
        }
        return { ok: true, value: await response.json(), error: "" };
    } catch (err) {
        return { ok: false, value: null, error: err instanceof Error ? err.message : "Request failed." };
    }
}

function asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray<T>(value: unknown, fallback: T[] = []): T[] {
    return Array.isArray(value) ? value as T[] : fallback;
}

function num(value: unknown, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function str(value: unknown, fallback = "") {
    return typeof value === "string" ? value : fallback;
}

function normalizeSummary(value: unknown): PortfolioSummary {
    const raw = asRecord(value);
    const rawSettings = asRecord(raw.settings);
    return {
        ...emptySummary,
        ...raw,
        account_id: num(raw.account_id, emptySummary.account_id),
        cash_balance: num(raw.cash_balance),
        available_bankroll: num(raw.available_bankroll),
        invested_value: num(raw.invested_value),
        total_equity: num(raw.total_equity),
        realized_pnl: num(raw.realized_pnl),
        unrealized_pnl: num(raw.unrealized_pnl),
        all_time_pnl: num(raw.all_time_pnl),
        current_cycle_pnl: num(raw.current_cycle_pnl),
        drawdown_pct: num(raw.drawdown_pct),
        exposure_pct: num(raw.exposure_pct),
        open_positions: num(raw.open_positions),
        reset_count: num(raw.reset_count),
        seconds_since_last_reset: raw.seconds_since_last_reset === null ? null : num(raw.seconds_since_last_reset),
        positions: asArray<Position>(raw.positions),
        recent_orders: asArray<Order>(raw.recent_orders),
        settings: {
            ...emptySummary.settings,
            ...rawSettings,
            autonomous_enabled: Boolean(rawSettings.autonomous_enabled),
            research_enabled: Boolean(rawSettings.research_enabled),
            trigger_monitor_enabled: Boolean(rawSettings.trigger_monitor_enabled),
            global_crew_enabled: Boolean(rawSettings.global_crew_enabled),
            global_research_enabled: Boolean(rawSettings.global_research_enabled),
            global_trigger_monitor_enabled: Boolean(rawSettings.global_trigger_monitor_enabled),
            research_interval_seconds: num(rawSettings.research_interval_seconds, emptySummary.settings.research_interval_seconds),
            max_position_pct: num(rawSettings.max_position_pct, emptySummary.settings.max_position_pct),
            max_daily_loss_pct: num(rawSettings.max_daily_loss_pct, emptySummary.settings.max_daily_loss_pct),
            max_open_positions: num(rawSettings.max_open_positions, emptySummary.settings.max_open_positions),
            max_trades_per_day: num(rawSettings.max_trades_per_day, emptySummary.settings.max_trades_per_day),
            bankroll_reset_drawdown_pct: num(rawSettings.bankroll_reset_drawdown_pct, emptySummary.settings.bankroll_reset_drawdown_pct),
            default_starting_bankroll: num(rawSettings.default_starting_bankroll, emptySummary.settings.default_starting_bankroll),
            ai_paper_account_id: rawSettings.ai_paper_account_id === null ? null : num(rawSettings.ai_paper_account_id, 0),
        },
    } as PortfolioSummary;
}

function normalizeRuntime(value: unknown): RuntimeStatus | null {
    const raw = asRecord(value);
    if (!Object.keys(raw).length) return null;
    return {
        enabled: Boolean(raw.enabled),
        available: Boolean(raw.available),
        provider: str(raw.provider, "ollama"),
        model: str(raw.model),
        status: str(raw.status, "unknown"),
        message: str(raw.message, "Crew runtime status is unavailable."),
        model_routing: normalizeRouting(raw.model_routing),
    };
}

function normalizeModels(value: unknown): CrewModelsPayload {
    const raw = asRecord(value);
    return {
        available: Boolean(raw.available),
        status: str(raw.status, "unknown"),
        message: str(raw.message, "Model list is unavailable."),
        provider: str(raw.provider, "ollama"),
        base_url: str(raw.base_url),
        models: asArray<CrewModel>(raw.models),
        routing: normalizeRouting(raw.routing),
        current_model: str(raw.current_model),
    };
}

function normalizeRouting(value: unknown): ModelRoutingPayload {
    const raw = asRecord(value);
    const selected = asRecord(raw.selected);
    const effective = asRecord(raw.effective);
    return {
        selected: {
            default: typeof selected.default === "string" ? selected.default : null,
            research: typeof selected.research === "string" ? selected.research : null,
            thesis: typeof selected.thesis === "string" ? selected.thesis : null,
            risk: typeof selected.risk === "string" ? selected.risk : null,
            trade: typeof selected.trade === "string" ? selected.trade : null,
        },
        effective: {
            default: str(effective.default, emptyRoutingPayload.effective.default),
            research: str(effective.research, str(effective.default)),
            thesis: str(effective.thesis, str(effective.default)),
            risk: str(effective.risk, str(effective.default)),
            trade: str(effective.trade, str(effective.default)),
        },
        fallback_model: str(raw.fallback_model),
    };
}

function normalizeDiagnostics(value: unknown): NoTradeDiagnostics | null {
    const raw = asRecord(value);
    if (!Object.keys(raw).length) return null;
    const latestRun = asRecord(raw.latest_run);
    const latestFailure = asRecord(raw.latest_model_failure);
    return {
        active_thesis_count: num(raw.active_thesis_count),
        latest_run: Object.keys(latestRun).length ? latestRun as NoTradeDiagnostics["latest_run"] : null,
        latest_model_failure: Object.keys(latestFailure).length ? latestFailure as NoTradeDiagnostics["latest_model_failure"] : null,
        blockers: asArray<string>(raw.blockers).filter((item) => typeof item === "string"),
        recommended_action: str(raw.recommended_action),
    };
}

function normalizeModelPerformance(value: ModelPerformance): ModelPerformance {
    return {
        ...value,
        calls: num(value.calls),
        successes: num(value.successes),
        failures: num(value.failures),
        timeouts: num(value.timeouts),
        approved: num(value.approved),
        rejected: num(value.rejected),
        validation_failures: num(value.validation_failures),
        avg_latency_ms: num(value.avg_latency_ms),
        theses_created: num(value.theses_created),
        trades_approved: num(value.trades_approved),
        trades_rejected: num(value.trades_rejected),
        success_rate_pct: num(value.success_rate_pct),
        timeout_rate_pct: num(value.timeout_rate_pct),
    };
}

function chooseFastModel(models: CrewModel[]) {
    const names = models.map((model) => model.name).filter(Boolean);
    for (const preferred of ["gpt-oss:20b", "qwen2.5:32b"]) {
        if (names.includes(preferred)) return preferred;
    }
    const ranked = models
        .filter((model) => !`${model.family || ""} ${model.name}`.toLowerCase().includes("vision"))
        .sort((a, b) => (a.size || Number.MAX_SAFE_INTEGER) - (b.size || Number.MAX_SAFE_INTEGER));
    return ranked[0]?.name || names[0] || "";
}

function TraceRow({ event, debugOpen }: { event: TraceEvent; debugOpen: boolean }) {
    return (
        <div className="rounded border border-white/10 bg-black/30 p-4">
            <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                <div>
                    <div className="flex flex-wrap items-center gap-2">
                        <StatusPill status={event.status} />
                        <span className="text-xs text-gray-500">{event.role}</span>
                        {event.symbol ? <span className="font-mono text-xs text-cyan-200">{event.exchange?.toUpperCase()}:{event.symbol}</span> : null}
                        {event.llm_model ? <span className="font-mono text-xs text-purple-200">{event.model_role || "model"}: {event.llm_model}</span> : null}
                    </div>
                    <div className="mt-2 text-sm font-medium text-white">{event.public_summary}</div>
                </div>
                <div className="text-xs text-gray-500">{formatDate(event.created_at)}</div>
            </div>
            {event.rationale ? <p className="mt-2 text-sm text-gray-300">{event.rationale}</p> : null}
            {event.blocker_reason ? (
                <div className="mt-2 rounded border border-yellow-500/20 bg-yellow-500/10 p-2 text-xs text-yellow-100">
                    {event.blocker_reason}
                </div>
            ) : null}
            {event.validation_error ? (
                <div className="mt-2 rounded border border-red-500/20 bg-red-500/10 p-2 text-xs text-red-100">
                    {event.validation_error}
                </div>
            ) : null}
            {Object.keys(event.evidence || {}).length > 0 ? (
                <pre className="mt-3 max-h-40 overflow-auto rounded bg-black/40 p-3 text-[11px] text-gray-300">
                    {JSON.stringify(event.evidence, null, 2)}
                </pre>
            ) : null}
            {debugOpen && (event.prompt || event.raw_model_json) ? (
                <div className="mt-3 space-y-2">
                    {event.prompt ? (
                        <pre className="max-h-48 overflow-auto rounded border border-white/10 bg-black/60 p-3 text-[11px] text-gray-300">
                            {event.prompt}
                        </pre>
                    ) : null}
                    {event.raw_model_json ? (
                        <pre className="max-h-48 overflow-auto rounded border border-white/10 bg-black/60 p-3 text-[11px] text-gray-300">
                            {JSON.stringify(event.raw_model_json, null, 2)}
                        </pre>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
    return (
        <section className="overflow-hidden rounded-lg border border-white/10 bg-white/[0.02]">
            <div className="border-b border-white/10 px-5 py-4">
                <h2 className="font-semibold text-white">{title}</h2>
            </div>
            {children}
        </section>
    );
}

function Metric({ icon: Icon, label, value, delta }: { icon: typeof Bot; label: string; value: string | number; delta?: number }) {
    return (
        <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
            <Icon className="mb-3 h-5 w-5 text-cyan-300" />
            <div className="text-xs text-gray-500">{label}</div>
            <div className="mt-1 truncate font-mono text-2xl font-semibold text-white">{value}</div>
            {delta !== undefined && (
                <div className={cn("mt-2 text-xs", delta >= 0 ? "text-green-300" : "text-red-300")}>
                    {delta >= 0 ? "+" : ""}{formatCurrency(delta)}
                </div>
            )}
        </div>
    );
}

function Toggle({ enabled, onClick }: { enabled: boolean; onClick: () => void }) {
    const Icon = enabled ? ToggleRight : ToggleLeft;
    return (
        <button onClick={onClick} className={cn("rounded p-1", enabled ? "text-cyan-300" : "text-gray-500")} aria-pressed={enabled}>
            <Icon className="h-8 w-8" />
        </button>
    );
}

function Info({ label, value }: { label: string; value: string | number }) {
    return (
        <div>
            <div className="text-[11px] uppercase text-gray-500">{label}</div>
            <div className="truncate font-mono text-sm text-white">{value}</div>
        </div>
    );
}

function Empty({ text }: { text: string }) {
    return <div className="px-5 py-8 text-sm text-gray-500">{text}</div>;
}

function StatusPill({ status }: { status: string }) {
    const tone =
        ["executed", "completed", "available", "runtime_ready", "buy", "active", "entry_triggered"].includes(status)
            ? "border-green-500/30 bg-green-500/10 text-green-200"
            : ["rejected", "failed", "unavailable", "stop_loss", "sell", "expired", "cancelled"].includes(status)
                ? "border-red-500/30 bg-red-500/10 text-red-200"
                : status.includes("running")
                    ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-200"
                    : "border-yellow-500/30 bg-yellow-500/10 text-yellow-200";
    return <span className={cn("rounded border px-2 py-1 text-xs font-medium capitalize", tone)}>{status.replaceAll("_", " ")}</span>;
}

function DualLineChart({ points }: { points: EquityPoint[] }) {
    const safePoints = points.length ? points : [];
    const width = 720;
    const height = 260;
    const padding = 26;
    const values = safePoints.flatMap((point) => [Number(point.equity || 0), Number(point.cash_balance || 0), Number(point.invested_value || 0)]);
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 1);
    const range = Math.max(max - min, 1);
    const pathFor = (key: keyof Pick<EquityPoint, "equity" | "cash_balance" | "invested_value">) =>
        safePoints.map((point, idx) => {
            const x = padding + (idx / Math.max(safePoints.length - 1, 1)) * (width - padding * 2);
            const y = height - padding - ((Number(point[key] || 0) - min) / range) * (height - padding * 2);
            return `${idx === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
        }).join(" ");

    return (
        <div>
            <svg viewBox={`0 0 ${width} ${height}`} className="h-72 w-full overflow-visible">
                <rect x="0" y="0" width={width} height={height} rx="8" className="fill-black/30" />
                <path d={pathFor("equity")} fill="none" stroke="#22d3ee" strokeWidth="3" />
                <path d={pathFor("cash_balance")} fill="none" stroke="#4ade80" strokeWidth="2" strokeDasharray="5 5" />
                <path d={pathFor("invested_value")} fill="none" stroke="#f59e0b" strokeWidth="2" />
            </svg>
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-gray-400">
                <Legend color="bg-cyan-400" label="Equity" />
                <Legend color="bg-green-400" label="Cash" />
                <Legend color="bg-amber-400" label="Invested" />
            </div>
        </div>
    );
}

function Legend({ color, label }: { color: string; label: string }) {
    return (
        <div className="flex items-center gap-2">
            <span className={cn("h-2 w-6 rounded", color)} />
            {label}
        </div>
    );
}

function formatCurrency(value: number) {
    return Number(value || 0).toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
    });
}

function formatPrice(value: number | null | undefined) {
    if (value === null || value === undefined) return "--";
    return Number(value).toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: value > 100 ? 2 : 6,
    });
}

function formatDate(value: string | null | undefined) {
    if (!value) return "--";
    const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return "--";
    return new Intl.DateTimeFormat(undefined, {
        year: "2-digit",
        month: "numeric",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
    }).format(date);
}

function formatDuration(seconds: number | null) {
    if (seconds === null) return "Never";
    if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
}

function formatBytes(value: number | null | undefined) {
    if (!value) return "unknown size";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = value;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
        size /= 1024;
        index += 1;
    }
    return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
