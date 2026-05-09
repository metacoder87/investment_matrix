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
import { Accordion } from "@/components/Accordion";
import { DebugJson } from "@/components/DebugJson";
import { PortfolioDonutChart } from "@/components/crew/PortfolioDonutChart";
import { StrategyPerformanceBarChart } from "@/components/crew/StrategyPerformanceBarChart";

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
    active_research_tasks?: {
        id: number;
        status: string;
        max_symbols: number | null;
        selected_symbols: string[];
        summary: Record<string, unknown>;
        created_at: string | null;
    }[];
    latest_run: {
        id: number;
        status: string;
        mode?: string;
        max_symbols?: number | null;
        selected_symbols?: string[];
        summary: Record<string, unknown>;
        created_at: string | null;
    } | null;
    latest_research_run?: {
        id: number;
        status: string;
        summary: Record<string, unknown>;
        created_at: string | null;
    } | null;
    latest_formula_candidate?: {
        exchange: string;
        symbol: string;
        side: string;
        entry_score: number;
        price: number | null;
        created_at: string | null;
    } | null;
    latest_execution_blocker?: Partial<TraceEvent> | null;
    open_position_count?: number;
    unmanaged_position_count?: number;
    latest_repaired_position?: Partial<TraceEvent> | null;
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
    long_exposure: number;
    short_exposure: number;
    short_reserved_collateral: number;
    long_unrealized_pnl: number;
    short_unrealized_pnl: number;
    sleeve_cash: Record<"long" | "short", number>;
    sleeve_reserved_collateral: Record<"long" | "short", number>;
    sleeve_pnl: Record<"long" | "short", number>;
    sleeve_win_rates: Record<"long" | "short", number>;
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
    side?: string | null;
    sleeve?: string | null;
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
    side: string;
    quantity: number;
    avg_entry_price: number;
    last_price: number;
    market_value: number;
    cost_basis: number;
    reserved_collateral: number;
    take_profit?: number | null;
    stop_loss?: number | null;
    exit_health?: string | null;
    exit_source?: string | null;
    distance_to_take_profit_pct?: number | null;
    distance_to_stop_loss_pct?: number | null;
    equity_value?: number;
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

interface FormulaConfig {
    id: number;
    name: string;
    is_active: boolean;
    authority_mode: "approval_required" | "auto_apply_bounded";
    created_by: string;
    parameters: Record<string, unknown>;
    bounds: Record<string, { min: number; max: number }>;
    created_at: string | null;
    updated_at: string | null;
}

interface FormulaSuggestion {
    id: number;
    config_id: number;
    status: string;
    source: string;
    proposed_parameters: Record<string, unknown>;
    deterministic_evidence: Record<string, unknown>;
    ai_notes: string | null;
    applied_at: string | null;
    created_at: string | null;
    updated_at: string | null;
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
    reason_code?: string;
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
    long_exposure: 0,
    short_exposure: 0,
    short_reserved_collateral: 0,
    long_unrealized_pnl: 0,
    short_unrealized_pnl: 0,
    sleeve_cash: { long: 0, short: 0 },
    sleeve_reserved_collateral: { long: 0, short: 0 },
    sleeve_pnl: { long: 0, short: 0 },
    sleeve_win_rates: { long: 0, short: 0 },
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
    const [formulaConfig, setFormulaConfig] = useState<FormulaConfig | null>(null);
    const [formulaSuggestions, setFormulaSuggestions] = useState<FormulaSuggestion[]>([]);
    const [modelRouting, setModelRouting] = useState<Record<ModelRole, string>>(emptyModelRouting);
    const [modelRoutingDirty, setModelRoutingDirty] = useState(false);
    const [modelPerformance, setModelPerformance] = useState<ModelPerformance[]>([]);
    const [modelTestStatus, setModelTestStatus] = useState<string | null>(null);
    const [degraded, setDegraded] = useState<string[]>([]);
    const [debugOpen, setDebugOpen] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [activeTab, setActiveTab] = useState<"overview" | "portfolio" | "config" | "logs">("overview");

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
        if (activeTheses.length === 0 && !(diagnostics?.active_research_tasks?.length)) blockers.push("No active thesis is waiting on an entry target.");
        activity.slice(0, 8).forEach((event) => {
            if (event.blocker_reason && !blockers.includes(event.blocker_reason)) blockers.push(event.blocker_reason);
        });
        return blockers.slice(0, 8);
    }, [
        activeTheses.length,
        activity,
        diagnostics?.active_research_tasks,
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
    const formulaParameters = useMemo(() => asRecord(formulaConfig?.parameters), [formulaConfig]);
    const longFormulaParameters = useMemo(() => asRecord(formulaParameters.long), [formulaParameters]);
    const shortFormulaParameters = useMemo(() => asRecord(formulaParameters.short), [formulaParameters]);

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
            formulaConfigRes,
            formulaSuggestionsRes,
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
            fetchJson(`${base}/crew/formula-config`),
            fetchJson(`${base}/crew/formula-suggestions`),
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
            formulaConfigRes,
            formulaSuggestionsRes,
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
        if (formulaConfigRes.ok) setFormulaConfig(normalizeFormulaConfig(formulaConfigRes.value));
        setFormulaSuggestions(asArray<FormulaSuggestion>(formulaSuggestionsRes.value).map(normalizeFormulaSuggestion));
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

    const patchFormulaConfig = async (changes: Partial<FormulaConfig> & { parameters?: Record<string, unknown> }) => {
        setLoading(true);
        setError(null);
        setNotice(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/formula-config`, {
                method: "PATCH",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(changes),
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, "Unable to update formula settings."));
            const payload = await response.json();
            setFormulaConfig(normalizeFormulaConfig(payload));
            setNotice("Formula settings updated. Future crew decisions will use the active deterministic config.");
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to update formula settings.");
        } finally {
            setLoading(false);
        }
    };

    const patchFormulaParameter = async (path: string, value: string) => {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
            setError("Formula setting must be a number.");
            return;
        }
        await patchFormulaConfig({ parameters: buildNestedPatch(path, numeric) });
    };

    const handleSuggestion = async (suggestionId: number, action: "approve" | "reject") => {
        setLoading(true);
        setError(null);
        setNotice(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/formula-suggestions/${suggestionId}/${action}`, {
                method: "POST",
                credentials: "include",
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, `Unable to ${action} formula suggestion.`));
            setNotice(action === "approve" ? "Formula suggestion approved and applied." : "Formula suggestion rejected.");
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : `Unable to ${action} formula suggestion.`);
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
            setNotice(`AI bot started on ${(payload.primary_exchange || primaryExchange).toUpperCase()}. Formula-first research run #${payload.run_id || "new"} queued.`);
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
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ max_symbols: 3, execute_immediate: true }),
            });
            if (!runResponse.ok) throw new Error(await responseErrorMessage(runResponse, "Models saved and tested, but research could not be queued."));
            const queued = await runResponse.json();
            setNotice(`Model routing saved. Formula-first paper research run #${queued.run_id} was queued for ${queued.max_symbols} symbols.`);
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
            setNotice(`${result.model} produced a valid ${result.exchange?.toUpperCase()}:${result.symbol} thesis dry-run. Dry-run validates thesis JSON only; no paper trade is created.`);
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to run thesis dry-run.");
            await loadDashboard();
        } finally {
            setModelTestStatus(null);
            setLoading(false);
        }
    };

    const runPaperTradeNow = async () => {
        setLoading(true);
        setError(null);
        setNotice(null);
        setModelTestStatus("Queueing one-symbol formula-first paper run...");
        try {
            const response = await fetch(`${getApiBaseUrl()}/crew/research/run-now`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ max_symbols: 1, execute_immediate: true }),
            });
            if (!response.ok) throw new Error(await responseErrorMessage(response, "Unable to queue formula-first paper run."));
            const result = await response.json();
            setNotice(`Formula-first paper run #${result.run_id} queued for one symbol. The dashboard will show the paper order when guardrails pass.`);
            await loadDashboard();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to queue formula-first paper run.");
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

            {/* TAB BAR */}
            <div className="flex border-b border-white/10 overflow-x-auto scrollbar-hide">
                {(["overview", "portfolio", "config", "logs"] as const).map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={cn(
                            "px-6 py-3 text-sm font-medium uppercase tracking-wider transition-colors",
                            activeTab === tab
                                ? "border-b-2 border-cyan-400 text-cyan-400"
                                : "text-gray-500 hover:text-gray-300"
                        )}
                    >
                        {tab}
                    </button>
                ))}
            </div>

            {activeTab === "overview" && (
                <div className="space-y-6">
                    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                        <Metric icon={Wallet} label="Available bankroll" value={formatCurrency(summary.available_bankroll)} />
                        <Metric icon={LineChart} label="Total equity" value={formatCurrency(summary.total_equity)} delta={summary.current_cycle_pnl} />
                        <Metric icon={Target} label="Long exposure" value={formatCurrency(summary.long_exposure)} />
                        <Metric icon={Target} label="Short exposure" value={formatCurrency(summary.short_exposure)} />
                        <Metric icon={AlertTriangle} label="Drawdown" value={`${summary.drawdown_pct.toFixed(2)}%`} />
                        <Metric icon={ShieldCheck} label="All-time PnL" value={formatCurrency(summary.all_time_pnl)} delta={summary.all_time_pnl} />
                        <Metric icon={Bot} label="AI win rate" value={`${winRate.toFixed(1)}%`} />
                        <Metric icon={History} label="Bankroll resets" value={summary.reset_count} />
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

                        <Panel title="Strategy Performance">
                            <StrategyPerformanceBarChart strategies={strategies} />
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

                        <Panel title="Active Target Conditions">
                            <div className="grid gap-3 p-4">
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
                    </section>
                </div>
            )}

            {activeTab === "portfolio" && (
                <div className="space-y-6">
                    <section className="grid gap-4 xl:grid-cols-[1fr_1.5fr]">
                        <Panel title="Asset Allocation">
                            <PortfolioDonutChart cash={summary.cash_balance} invested={summary.invested_value} />
                        </Panel>

                        <Panel title="Autonomy Settings">
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
                            </div>
                        </Panel>
                    </section>

                    <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                        <Panel title="Owned Assets">
                            <div className="divide-y divide-white/5">
                                {positions.length === 0 ? (
                                    <Empty text="The AI team does not currently own any paper assets." />
                                ) : positions.map((position) => (
                                    <div key={`${position.exchange}:${position.symbol}`} className="grid gap-3 px-5 py-4 md:grid-cols-[1fr_0.75fr_0.75fr_0.7fr_1fr] md:items-center">
                                        <div>
                                            <div className="font-medium text-white">{position.symbol}</div>
                                            <div className="text-xs text-gray-500">
                                                {(position.side || "long").toUpperCase()} / {position.quantity.toFixed(6)} units
                                            </div>
                                        </div>
                                        <Info
                                            label={position.side === "short" ? "Collateral" : "Market value"}
                                            value={formatCurrency(position.side === "short" ? position.reserved_collateral : position.market_value)}
                                        />
                                        <Info label="Unrealized" value={formatCurrency(position.unrealized_pnl)} />
                                        <Info label="Return" value={`${position.return_pct.toFixed(2)}%`} />
                                        <div className="text-sm">
                                            <div className="text-xs uppercase tracking-wide text-gray-500">Exit plan</div>
                                            <div className="font-medium text-gray-100">
                                                {humanize(position.exit_health || "missing")} / {humanize(position.exit_source || "unknown")}
                                            </div>
                                            <div className="mt-1 text-xs text-gray-500">
                                                TP {formatPrice(position.take_profit)} ({formatTargetDistance(position.distance_to_take_profit_pct)}) / SL {formatPrice(position.stop_loss)} ({formatTargetDistance(position.distance_to_stop_loss_pct)})
                                            </div>
                                        </div>
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
                </div>
            )}

            {activeTab === "config" && (
                <div className="space-y-6">
                    <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                        <Panel title="Formula Settings">
                            <div className="space-y-4 p-5">
                                <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-white/10 bg-black/30 p-3">
                                    <div>
                                        <div className="text-sm font-medium text-white">{formulaConfig?.name || "Formula v1"}</div>
                                        <div className="text-xs text-gray-500">Active deterministic config</div>
                                    </div>
                                    <select
                                        value={formulaConfig?.authority_mode || "approval_required"}
                                        onChange={(event) => patchFormulaConfig({ authority_mode: event.target.value as FormulaConfig["authority_mode"] })}
                                        className="rounded border border-white/10 bg-black/50 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400"
                                        aria-label="Formula authority mode"
                                    >
                                        <option value="approval_required">Require approval</option>
                                        <option value="auto_apply_bounded">Auto-apply bounded</option>
                                    </select>
                                </div>
                                <div className="grid gap-3 md:grid-cols-2">
                                    <FormulaInput label="Entry floor" value={num(formulaParameters.entry_score_floor, 0.5)} step="0.01" onCommit={(value) => patchFormulaParameter("entry_score_floor", value)} />
                                    <FormulaInput label="Full size score" value={num(formulaParameters.full_size_score, 0.6)} step="0.01" onCommit={(value) => patchFormulaParameter("full_size_score", value)} />
                                    <FormulaInput label="ATR length" value={num(formulaParameters.atr_length, 14)} step="1" onCommit={(value) => patchFormulaParameter("atr_length", value)} />
                                    <FormulaInput label="RSI length" value={num(formulaParameters.rsi_length, 14)} step="1" onCommit={(value) => patchFormulaParameter("rsi_length", value)} />
                                    <FormulaInput label="Long target ATR" value={num(longFormulaParameters.target_atr_multiplier, 2)} step="0.05" onCommit={(value) => patchFormulaParameter("long.target_atr_multiplier", value)} />
                                    <FormulaInput label="Short target ATR" value={num(shortFormulaParameters.target_atr_multiplier, 1.4)} step="0.05" onCommit={(value) => patchFormulaParameter("short.target_atr_multiplier", value)} />
                                    <FormulaInput label="Long min profit" value={num(longFormulaParameters.min_profit_pct, 0.012)} step="0.001" onCommit={(value) => patchFormulaParameter("long.min_profit_pct", value)} />
                                    <FormulaInput label="Short min profit" value={num(shortFormulaParameters.min_profit_pct, 0.006)} step="0.001" onCommit={(value) => patchFormulaParameter("short.min_profit_pct", value)} />
                                </div>
                                <div className="rounded border border-white/10 bg-black/20 p-3 text-xs text-gray-400">
                                    <span className="text-gray-500">Decision path</span>
                                    <span className="ml-2 text-gray-200">Formula, backtests, guardrails</span>
                                </div>
                            </div>
                        </Panel>

                        <Panel title="Formula Suggestions">
                            <div className="max-h-[430px] divide-y divide-white/5 overflow-y-auto">
                                {formulaSuggestions.length === 0 ? (
                                    <Empty text="No formula tuning suggestions." />
                                ) : formulaSuggestions.map((suggestion) => (
                                    <div key={suggestion.id} className="space-y-3 px-5 py-4">
                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                            <div>
                                                <div className="font-medium text-white">{humanize(suggestion.source)}</div>
                                                <div className="text-xs text-gray-500">{formatDate(suggestion.created_at)}</div>
                                            </div>
                                            <StatusPill status={suggestion.status} />
                                        </div>
                                        <p className="text-sm text-gray-300">{suggestion.ai_notes || "No notes recorded."}</p>
                                        <div className="grid grid-cols-2 gap-3 text-sm">
                                            <Info label="Win rate" value={`${(num(suggestion.deterministic_evidence.win_rate) * 100).toFixed(1)}%`} />
                                            <Info label="Avg return" value={`${num(suggestion.deterministic_evidence.avg_return_pct).toFixed(2)}%`} />
                                        </div>
                                        {suggestion.status === "pending" ? (
                                            <div className="grid gap-2 sm:grid-cols-2">
                                                <button
                                                    onClick={() => handleSuggestion(suggestion.id, "approve")}
                                                    disabled={loading}
                                                    className="rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-50"
                                                >
                                                    Approve
                                                </button>
                                                <button
                                                    onClick={() => handleSuggestion(suggestion.id, "reject")}
                                                    disabled={loading}
                                                    className="rounded border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-gray-100 hover:bg-white/10 disabled:opacity-50"
                                                >
                                                    Reject
                                                </button>
                                            </div>
                                        ) : null}
                                    </div>
                                ))}
                            </div>
                        </Panel>
                    </section>

                    <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
                        <Panel title="AI Notes Models">
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
                                    <button
                                        onClick={runPaperTradeNow}
                                        disabled={loading}
                                        className="inline-flex w-full items-center justify-center gap-2 rounded border border-green-500/40 bg-green-500/10 px-3 py-2 text-sm font-medium text-green-100 hover:bg-green-500/20 disabled:opacity-50 sm:col-span-2"
                                    >
                                        <Play className="h-4 w-4" />
                                        Run paper trade now
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

                        <div className="space-y-4">
                            <Accordion
                                title="Downloaded Models"
                                summary={models?.models?.length ? `${models.models.length} models` : "0 models"}
                                defaultOpen={false}
                            >
                                <div className="space-y-3 p-5">
                                    <div className="text-xs text-gray-500">
                                        Ollama models available to the crew. Tap the View Debug button for the raw payload.
                                    </div>
                                    <div className="max-h-[420px] divide-y divide-white/5 overflow-y-auto rounded border border-white/10 bg-black/20 scrollbar-thin-cyan">
                                        {!models?.models?.length ? (
                                            <Empty text="No downloaded Ollama models were returned. Check that Ollama is reachable from the backend." />
                                        ) : models.models.map((model) => (
                                            <div key={model.name} className="px-4 py-3">
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
                                    <DebugJson value={models ?? {}} label="View Debug" maxHeight="20rem" />
                                </div>
                            </Accordion>

                            <Panel title="Model Performance">
                                <div className="overflow-x-auto">
                                    <table className="min-w-full divide-y divide-white/10 text-sm">
                                        <thead className="bg-white/[0.03] text-xs uppercase text-gray-500">
                                            <tr>
                                                <th className="px-4 py-3 text-left font-medium">Model</th>
                                                <th className="px-4 py-3 text-left font-medium">Role</th>
                                                <th className="px-4 py-3 text-right font-medium">Calls</th>
                                                <th className="px-4 py-3 text-right font-medium">Success</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-white/5">
                                            {modelPerformance.length === 0 ? (
                                                <tr>
                                                    <td colSpan={4}>
                                                        <Empty text="No model calls have been recorded yet." />
                                                    </td>
                                                </tr>
                                            ) : modelPerformance.map((row) => (
                                                <tr key={`${row.role}:${row.model}`} className="text-gray-300">
                                                    <td className="max-w-[200px] truncate px-4 py-3 font-mono text-xs text-white">{row.model}</td>
                                                    <td className="px-4 py-3">{row.role}</td>
                                                    <td className="px-4 py-3 text-right font-mono">{row.calls}</td>
                                                    <td className="px-4 py-3 text-right font-mono">{row.success_rate_pct.toFixed(1)}%</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </Panel>
                        </div>
                    </section>
                </div>
            )}

            {activeTab === "logs" && (
                <div className="space-y-6">
                    <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
                        <Panel title="Why No Trade Yet?">
                            <div className="space-y-3 p-5">
                                <div className="flex flex-wrap items-center gap-2">
                                    <StatusPill status={botState.toLowerCase().replace(" ", "_")} />
                                    <StatusPill status={summary.settings.trade_cadence_mode || "aggressive_paper"} />
                                    <span className="text-xs text-gray-500">{activeTheses.length} active theses</span>
                                </div>
                                {diagnostics?.active_research_tasks?.length ? (
                                    <div className="rounded border border-cyan-500/20 bg-cyan-500/10 p-3 text-sm text-cyan-100">
                                        Research run #{diagnostics.active_research_tasks[0].id} is {diagnostics.active_research_tasks[0].status}.
                                        {typeof diagnostics.active_research_tasks[0].summary?.current_symbol === "string"
                                            ? ` Current symbol: ${diagnostics.active_research_tasks[0].summary.current_symbol}.`
                                            : " Waiting for the worker to pick it up."}
                                    </div>
                                ) : null}
                                {diagnostics?.latest_formula_candidate ? (
                                    <div className="rounded border border-white/10 bg-black/30 p-3 text-sm text-gray-200">
                                        Latest formula candidate: {diagnostics.latest_formula_candidate.exchange.toUpperCase()}:{diagnostics.latest_formula_candidate.symbol}
                                        {" "}{diagnostics.latest_formula_candidate.side.toUpperCase()} score {diagnostics.latest_formula_candidate.entry_score.toFixed(2)}
                                        {" "}at {formatPrice(diagnostics.latest_formula_candidate.price)}.
                                    </div>
                                ) : null}
                                {currentBlockers.length === 0 ? (
                                    <div className="rounded border border-green-500/20 bg-green-500/10 p-3 text-sm text-green-100">
                                        No current blocker found. Formula-first research will create and execute paper entries when data, backtest, and position guardrails pass.
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
                                {diagnostics?.open_position_count ? (
                                    <div className="rounded border border-white/10 bg-black/20 p-3 text-xs text-gray-300">
                                        Open paper positions: {diagnostics.open_position_count}
                                        {diagnostics.unmanaged_position_count ? ` / ${diagnostics.unmanaged_position_count} need exit repair` : " / exit plans managed"}
                                    </div>
                                ) : null}
                                {diagnostics?.latest_repaired_position ? (
                                    <div className="rounded border border-emerald-500/20 bg-emerald-500/10 p-3 text-xs text-emerald-100">
                                        Latest exit repair: {diagnostics.latest_repaired_position.symbol || "position"} / {String(asRecord(diagnostics.latest_repaired_position.evidence).exit_source || "formula")}
                                    </div>
                                ) : null}
                                {diagnostics?.latest_model_failure ? (
                                    <div className="rounded border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-100">
                                        Latest model issue: {diagnostics.latest_model_failure.role} / {diagnostics.latest_model_failure.model} / {diagnostics.latest_model_failure.status}
                                    </div>
                                ) : null}
                                {diagnostics?.latest_execution_blocker?.blocker_reason ? (
                                    <div className="rounded border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-100">
                                        Latest execution blocker: {diagnostics.latest_execution_blocker.blocker_reason}
                                    </div>
                                ) : null}
                            </div>
                        </Panel>

                        <Accordion
                            title="Decision Log"
                            summary={activity.length ? `${activity.length} events` : "0 events"}
                            defaultOpen={true}
                            controls={
                                <button
                                    onClick={() => setDebugOpen((value) => !value)}
                                    className="inline-flex items-center gap-2 rounded border border-primary/30 bg-primary/5 px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-primary hover:bg-primary/10"
                                >
                                    <Terminal className="h-3.5 w-3.5" />
                                    {debugOpen ? "Hide Debug" : "View Debug"}
                                </button>
                            }
                        >
                            <div className="p-5">
                                <div className="mb-3 text-xs text-gray-500">
                                    Structured rationale, evidence, and blockers from the local AI team.
                                </div>
                                <div className="max-h-[520px] space-y-3 overflow-y-auto pr-1 scrollbar-thin-cyan">
                                    {activity.length === 0 ? (
                                        <Empty text="No AI activity recorded yet. Start the bot or wait for the next scheduled research cycle." />
                                    ) : activity.map((event) => (
                                        <TraceRow key={event.id} event={event} debugOpen={debugOpen} />
                                    ))}
                                </div>
                            </div>
                        </Accordion>
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
                </div>
            )}
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

function buildNestedPatch(path: string, value: number): Record<string, unknown> {
    const parts = path.split(".").filter(Boolean);
    if (!parts.length) return {};
    const root: Record<string, unknown> = {};
    let cursor = root;
    parts.slice(0, -1).forEach((part) => {
        const next: Record<string, unknown> = {};
        cursor[part] = next;
        cursor = next;
    });
    cursor[parts[parts.length - 1]] = value;
    return root;
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
        long_exposure: num(raw.long_exposure),
        short_exposure: num(raw.short_exposure),
        short_reserved_collateral: num(raw.short_reserved_collateral),
        long_unrealized_pnl: num(raw.long_unrealized_pnl),
        short_unrealized_pnl: num(raw.short_unrealized_pnl),
        sleeve_cash: {
            long: num(asRecord(raw.sleeve_cash).long),
            short: num(asRecord(raw.sleeve_cash).short),
        },
        sleeve_reserved_collateral: {
            long: num(asRecord(raw.sleeve_reserved_collateral).long),
            short: num(asRecord(raw.sleeve_reserved_collateral).short),
        },
        sleeve_pnl: {
            long: num(asRecord(raw.sleeve_pnl).long),
            short: num(asRecord(raw.sleeve_pnl).short),
        },
        sleeve_win_rates: {
            long: num(asRecord(raw.sleeve_win_rates).long),
            short: num(asRecord(raw.sleeve_win_rates).short),
        },
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
    const formulaCandidate = asRecord(raw.latest_formula_candidate);
    const executionBlocker = asRecord(raw.latest_execution_blocker);
    const repairedPosition = asRecord(raw.latest_repaired_position);
    return {
        active_thesis_count: num(raw.active_thesis_count),
        active_research_tasks: asArray(raw.active_research_tasks) as NoTradeDiagnostics["active_research_tasks"],
        latest_run: Object.keys(latestRun).length ? latestRun as NoTradeDiagnostics["latest_run"] : null,
        latest_research_run: Object.keys(asRecord(raw.latest_research_run)).length
            ? asRecord(raw.latest_research_run) as NoTradeDiagnostics["latest_research_run"]
            : null,
        latest_formula_candidate: Object.keys(formulaCandidate).length
            ? formulaCandidate as NoTradeDiagnostics["latest_formula_candidate"]
            : null,
        latest_execution_blocker: Object.keys(executionBlocker).length
            ? executionBlocker as NoTradeDiagnostics["latest_execution_blocker"]
            : null,
        open_position_count: num(raw.open_position_count),
        unmanaged_position_count: num(raw.unmanaged_position_count),
        latest_repaired_position: Object.keys(repairedPosition).length
            ? repairedPosition as NoTradeDiagnostics["latest_repaired_position"]
            : null,
        latest_model_failure: Object.keys(latestFailure).length ? latestFailure as NoTradeDiagnostics["latest_model_failure"] : null,
        blockers: asArray<string>(raw.blockers).filter((item) => typeof item === "string"),
        recommended_action: str(raw.recommended_action),
    };
}

function normalizeFormulaConfig(value: unknown): FormulaConfig {
    const raw = asRecord(value);
    const authority = str(raw.authority_mode, "approval_required");
    return {
        id: num(raw.id),
        name: str(raw.name, "Formula v1"),
        is_active: Boolean(raw.is_active),
        authority_mode: authority === "auto_apply_bounded" ? "auto_apply_bounded" : "approval_required",
        created_by: str(raw.created_by, "system"),
        parameters: asRecord(raw.parameters),
        bounds: asRecord(raw.bounds) as FormulaConfig["bounds"],
        created_at: raw.created_at === null ? null : str(raw.created_at),
        updated_at: raw.updated_at === null ? null : str(raw.updated_at),
    };
}

function normalizeFormulaSuggestion(value: FormulaSuggestion): FormulaSuggestion {
    const raw = asRecord(value);
    return {
        id: num(raw.id),
        config_id: num(raw.config_id),
        status: str(raw.status, "pending"),
        source: str(raw.source, "deterministic_optimizer"),
        proposed_parameters: asRecord(raw.proposed_parameters),
        deterministic_evidence: asRecord(raw.deterministic_evidence),
        ai_notes: raw.ai_notes === null ? null : str(raw.ai_notes),
        applied_at: raw.applied_at === null ? null : str(raw.applied_at),
        created_at: raw.created_at === null ? null : str(raw.created_at),
        updated_at: raw.updated_at === null ? null : str(raw.updated_at),
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
                        {event.reason_code ? <span className="font-mono text-xs text-gray-500">{event.reason_code}</span> : null}
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

function FormulaInput({ label, value, step, onCommit }: { label: string; value: number; step: string; onCommit: (value: string) => void }) {
    return (
        <label className="block rounded border border-white/10 bg-black/20 p-3">
            <span className="text-[11px] uppercase text-gray-500">{label}</span>
            <input
                key={`${label}:${value}`}
                type="number"
                step={step}
                defaultValue={value}
                onBlur={(event) => onCommit(event.currentTarget.value)}
                className="mt-2 w-full rounded border border-white/10 bg-black/50 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400"
            />
        </label>
    );
}

function Empty({ text }: { text: string }) {
    return <div className="px-5 py-8 text-sm text-gray-500">{text}</div>;
}

function StatusPill({ status }: { status: string }) {
    const tone =
        ["executed", "completed", "available", "runtime_ready", "buy", "short", "cover", "active", "entry_triggered"].includes(status)
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

function formatTargetDistance(value: number | null | undefined) {
    if (value === null || value === undefined) return "--";
    return `${Number(value).toFixed(2)}%`;
}

function humanize(value: string) {
    return value.replaceAll("_", " ");
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
