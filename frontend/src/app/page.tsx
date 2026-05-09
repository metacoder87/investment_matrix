"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import {
    Activity,
    AlertTriangle,
    ArrowUpRight,
    Bot,
    LineChart as LineChartIcon,
    PercentCircle,
    Target,
    Terminal,
    Wallet,
} from "lucide-react";
import { getApiBaseUrl } from "@/utils/api";
import { cn } from "@/utils/cn";
import { PositionsTable } from "@/components/dashboard/PositionsTable";
import { ThesesList } from "@/components/dashboard/ThesesList";
import { ActivityFeed } from "@/components/dashboard/ActivityFeed";
import {
    PortfolioSummary,
    EquityPoint,
    Position,
    ThesisLite,
    TraceEventLite,
    DashboardOrder,
} from "@/types/dashboard";

/* ---------- Types (mirrors crew/portfolio/summary endpoint) ---------- */



const emptySummary: PortfolioSummary = {
    source: "ai",
    portfolio_count: 0,
    available_bankroll: 0,
    cash_balance: 0,
    invested_value: 0,
    total_cost: 0,
    total_equity: 0,
    long_exposure: 0,
    short_exposure: 0,
    realized_pnl: 0,
    unrealized_pnl: 0,
    all_time_pnl: 0,
    current_cycle_pnl: 0,
    drawdown_pct: 0,
    exposure_pct: 0,
    open_positions: 0,
    sleeve_win_rates: { long: 0, short: 0 },
    closed_win_rate: null,
    closed_trade_count: 0,
    closed_wins: 0,
    closed_losses: 0,
    positions: [],
    recent_orders: [],
};

/* ---------- Helpers ---------- */

const num = (v: unknown, fallback = 0) => {
    const n = typeof v === "string" ? parseFloat(v) : (v as number);
    return Number.isFinite(n) ? n : fallback;
};

function formatCurrency(value: number) {
    return Number(value || 0).toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
    });
}

function safeFetch<T>(url: string): Promise<T | null> {
    return fetch(url, { credentials: "include" })
        .then((r) => {
            if (!r.ok) {
                // Log once per failed call so a quiet dashboard doesn't hide a broken backend.
                if (typeof window !== "undefined") {
                    console.warn(`[Dashboard] ${url} -> ${r.status}`);
                }
                return null;
            }
            return r.json() as Promise<T>;
        })
        .catch((err) => {
            if (typeof window !== "undefined") {
                console.warn(`[Dashboard] ${url} fetch failed`, err);
            }
            return null;
        });
}

function asArray<T>(value: unknown): T[] {
    return Array.isArray(value) ? (value as T[]) : [];
}

function normalizeSummary(value: unknown, source: "ai" | "user"): PortfolioSummary {
    const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
    const sleeve = (raw.sleeve_win_rates ?? {}) as Record<string, unknown>;
    return {
        ...emptySummary,
        source,
        portfolio_count: num(raw.portfolio_count),
        available_bankroll: num(raw.available_bankroll),
        cash_balance: num(raw.cash_balance),
        invested_value: num(raw.invested_value),
        total_cost: num(raw.total_cost, num(raw.invested_value)),
        total_equity: num(raw.total_equity),
        long_exposure: num(raw.long_exposure),
        short_exposure: num(raw.short_exposure),
        realized_pnl: num(raw.realized_pnl),
        unrealized_pnl: num(raw.unrealized_pnl),
        all_time_pnl: num(raw.all_time_pnl),
        current_cycle_pnl: num(raw.current_cycle_pnl),
        drawdown_pct: num(raw.drawdown_pct),
        exposure_pct: num(raw.exposure_pct),
        open_positions: num(raw.open_positions),
        sleeve_win_rates: {
            long: num(sleeve.long),
            short: num(sleeve.short),
        },
        closed_win_rate: raw.closed_win_rate === null || raw.closed_win_rate === undefined ? null : num(raw.closed_win_rate),
        closed_trade_count: num(raw.closed_trade_count),
        closed_wins: num(raw.closed_wins),
        closed_losses: num(raw.closed_losses),
        positions: asArray<Position>(raw.positions),
        recent_orders: asArray<DashboardOrder>(raw.recent_orders),
    };
}

/* ---------- Dashboard ---------- */

export default function DashboardPage() {
    const { isAuthenticated, isLoading: authLoading } = useAuth();
    const [tradeView, setTradeView] = useState<"ai" | "user">("ai");
    const [summary, setSummary] = useState<PortfolioSummary>(emptySummary);
    const [equity, setEquity] = useState<EquityPoint[]>([]);
    const [positions, setPositions] = useState<Position[]>([]);
    const [theses, setTheses] = useState<ThesisLite[]>([]);
    const [activity, setActivity] = useState<TraceEventLite[]>([]);
    const [userOrders, setUserOrders] = useState<DashboardOrder[]>([]);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        const base = getApiBaseUrl();
        if (tradeView === "user") {
            const s = await safeFetch<Record<string, unknown>>(`${base}/portfolio/dashboard`);
            return {
                s,
                e: [] as EquityPoint[],
                p: asArray<Position>(s?.positions),
                t: [] as ThesisLite[],
                a: [] as TraceEventLite[],
                o: asArray<DashboardOrder>(s?.recent_orders),
            };
        }

        const [s, e, p, t, a] = await Promise.all([
            safeFetch<Record<string, unknown>>(`${base}/crew/portfolio/summary`),
            safeFetch<EquityPoint[]>(`${base}/crew/portfolio/equity`),
            safeFetch<Position[]>(`${base}/crew/portfolio/positions`),
            safeFetch<ThesisLite[]>(`${base}/crew/theses`),
            safeFetch<TraceEventLite[]>(`${base}/crew/activity?limit=5&debug=false`),
        ]);
        return { s, e, p, t, a, o: [] as DashboardOrder[] };
    }, [tradeView]);

    useEffect(() => {
        // Don't poll until we know whether the user is logged in.
        // Anonymous visitors at "/" would otherwise get a 401-loop on
        // /crew/* endpoints every 30 seconds.
        if (authLoading) return;
        if (!isAuthenticated) {
            setLoading(false);
            return;
        }

        let alive = true;
        const refresh = async () => {
            // Skip work when the tab is in the background. A long-open tab
            // shouldn't hammer the API just to keep stale numbers warm.
            if (typeof document !== "undefined" && document.hidden) return;
            setLoading(true);
            const { s, e, p, t, a, o } = await load();
            if (!alive) return;
            if (s) {
                setSummary(normalizeSummary(s, tradeView));
            } else if (tradeView === "user") {
                setSummary({ ...emptySummary, source: "user" });
            }
            if (Array.isArray(e)) setEquity(e);
            if (Array.isArray(p)) setPositions(p);
            if (Array.isArray(t)) setTheses(t);
            if (Array.isArray(a)) setActivity(a);
            if (Array.isArray(o)) setUserOrders(o);
            setLoading(false);
        };

        refresh();
        const id = window.setInterval(refresh, 30_000);

        // When the tab returns to visible, refresh immediately so the user
        // doesn't see stale data while waiting for the next tick.
        const onVisible = () => {
            if (!document.hidden) refresh();
        };
        document.addEventListener("visibilitychange", onVisible);

        return () => {
            alive = false;
            window.clearInterval(id);
            document.removeEventListener("visibilitychange", onVisible);
        };
    }, [load, isAuthenticated, authLoading]);

    const winRate = useMemo(() => {
        const long = summary.sleeve_win_rates.long;
        const short = summary.sleeve_win_rates.short;
        const avg = ((long || 0) + (short || 0)) / (long && short ? 2 : long || short ? 1 : 1);
        return Number.isFinite(avg) ? avg * 100 : 0;
    }, [summary]);

    const userWinRate = summary.closed_win_rate === null || summary.closed_win_rate === undefined
        ? null
        : summary.closed_win_rate * 100;
    const isUserView = tradeView === "user";
    const pnlPositive = summary.current_cycle_pnl >= 0;
    const hasOpenPositions = summary.open_positions > 0;
    const primaryValue = isUserView ? summary.total_equity : summary.available_bankroll;
    const primaryLabel = isUserView ? "Portfolio Value" : "Bankroll";
    const primarySub = isUserView
        ? `Cost basis ${formatCurrency(summary.total_cost ?? summary.invested_value)}`
        : `Equity ${formatCurrency(summary.total_equity)}`;
    const winLabel = isUserView ? "Closed Win Rate" : "Win Rate";
    const winValue = isUserView ? (userWinRate === null ? "N/A" : `${userWinRate.toFixed(1)}%`) : `${winRate.toFixed(1)}%`;
    const winSub = isUserView
        ? `${summary.closed_trade_count ?? 0} closed trades`
        : `L ${(summary.sleeve_win_rates.long * 100).toFixed(0)}% / S ${(summary.sleeve_win_rates.short * 100).toFixed(0)}%`;
    const positionsLabel = isUserView ? "Open Holdings" : "Open Positions";
    const positionsSub = isUserView
        ? `${formatCurrency(summary.long_exposure)} market value`
        : `Exposure ${summary.exposure_pct.toFixed(1)}%`;
    const pnlLabel = isUserView ? "Total P&L" : "Cycle P&L";
    const pnlSub = isUserView
        ? `Realized ${formatCurrency(summary.realized_pnl)}`
        : `Drawdown ${summary.drawdown_pct.toFixed(2)}%`;

    return (
        <div className="mx-auto max-w-[1600px] space-y-6 p-4 md:p-8">
            {/* Header */}
            <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div>
                    <h1 className="font-mono text-3xl font-semibold uppercase tracking-wider text-white neon-text">
                        Command Deck
                    </h1>
                    <p className="mt-1 text-sm text-gray-400">
                        High-level KPIs from AI and manual trading activity. For dense market data, head to{" "}
                        <Link href="/market" className="text-primary hover:underline">
                            Market <ArrowUpRight className="-mt-0.5 inline h-3.5 w-3.5" />
                        </Link>
                        .
                    </p>
                </div>
                <div
                    role="tablist"
                    aria-label="Trade data source"
                    className="inline-flex rounded border border-white/10 bg-white/5 p-1"
                >
                    {[
                        { id: "ai" as const, label: "AI Trades", icon: Bot },
                        { id: "user" as const, label: "User Trades", icon: Wallet },
                    ].map(({ id, label, icon: Icon }) => (
                        <button
                            key={id}
                            type="button"
                            role="tab"
                            aria-selected={tradeView === id}
                            onClick={() => setTradeView(id)}
                            className={cn(
                                "inline-flex items-center gap-2 rounded px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition",
                                tradeView === id
                                    ? "bg-primary/20 text-primary shadow-neon-cyan"
                                    : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                            )}
                        >
                            <Icon className="h-3.5 w-3.5" />
                            {label}
                        </button>
                    ))}
                </div>
                <div className="rounded border border-primary/20 bg-primary/5 px-3 py-2 font-mono text-xs text-primary">
                    CryptoInsight Terminal v1.0.0 — {loading ? "syncing…" : "live"}
                </div>
            </div>

            {/* KPI grid */}
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <KpiCard
                    icon={Wallet}
                    label={primaryLabel}
                    value={formatCurrency(primaryValue)}
                    sub={primarySub}
                    accent="cyan"
                />
                <KpiCard
                    icon={PercentCircle}
                    label={winLabel}
                    value={winValue}
                    sub={winSub}
                    accent="green"
                />
                <KpiCard
                    icon={Target}
                    label={positionsLabel}
                    value={String(summary.open_positions)}
                    sub={positionsSub}
                    accent={hasOpenPositions ? "pulse" : "cyan"}
                />
                <KpiCard
                    icon={pnlPositive ? Activity : AlertTriangle}
                    label={pnlLabel}
                    value={formatCurrency(summary.current_cycle_pnl)}
                    sub={pnlSub}
                    accent={pnlPositive ? "green" : "pink"}
                />
            </section>

            {/* Chart + secondary */}
            <section className="grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
                <div className="neo-card kpi-shimmer">
                    <header className="flex items-center justify-between border-b border-white/10 px-5 py-3">
                        <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                            <LineChartIcon className="h-4 w-4 text-primary" />
                            {isUserView ? "Portfolio Snapshot" : "Equity Curve"}
                        </h2>
                        <span className="font-mono text-[11px] text-gray-500">
                            {isUserView ? `${summary.portfolio_count ?? 0} portfolios` : `${equity.length} pts`}
                        </span>
                    </header>
                    <div className="p-5">
                        <EquitySpark
                            points={isUserView ? [] : equity}
                            fallback={summary}
                            emptyLabel={isUserView ? "Current value snapshot" : "Waiting for cycle data..."}
                        />
                    </div>
                </div>

                <div className="neo-card">
                    <header className="border-b border-white/10 px-5 py-3">
                        <h2 className="font-mono text-sm uppercase tracking-wider text-white">
                            Quick Links
                        </h2>
                    </header>
                    <div className="grid gap-2 p-5 text-sm">
                        <QuickLink href="/market" icon={LineChartIcon} label="Market overview" />
                        <QuickLink href="/crew" icon={Bot} label="AI Crew console" />
                        <QuickLink href="/portfolio" icon={Wallet} label="Portfolio" />
                        <QuickLink href="/paper" icon={Target} label="Paper trading" />
                    </div>
                </div>
            </section>

            {/* Extended Dashboard Components */}
            <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
                {isUserView ? (
                    <>
                        <div className="flex flex-col gap-4">
                            <PositionsTable positions={positions} title="Open Holdings" emptyText="No Open Holdings" />
                            <PortfolioContextPanel summary={summary} />
                        </div>
                        <div className="h-[600px] xl:h-auto">
                            <RecentTradesList orders={userOrders} />
                        </div>
                    </>
                ) : (
                    <>
                        <div className="flex flex-col gap-4">
                            <PositionsTable positions={positions} />
                            <ThesesList theses={theses} />
                        </div>
                        <div className="h-[600px] xl:h-auto">
                            <ActivityFeed activity={activity} />
                        </div>
                    </>
                )}
            </section>
        </div>
    );
}

/* ---------- Subcomponents ---------- */

type KpiAccent = "cyan" | "green" | "pink" | "amber" | "pulse";

function KpiCard({
    icon: Icon,
    label,
    value,
    sub,
    accent = "cyan",
}: {
    icon: typeof Wallet;
    label: string;
    value: string;
    sub?: string;
    accent?: KpiAccent;
}) {
    const accentClass = {
        cyan: "text-primary",
        green: "text-accent neon-text-green",
        pink: "text-secondary",
        amber: "text-yellow-300",
        pulse: "text-accent neon-text-green",
    }[accent];

    return (
        <div
            className={cn(
                "neo-card kpi-shimmer p-5",
                accent === "pulse" && "neo-card-active"
            )}
        >
            <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] uppercase tracking-widest text-gray-400">
                    {label}
                </span>
                <Icon className={cn("h-4 w-4", accentClass)} />
            </div>
            <div className={cn("mt-3 truncate font-mono text-2xl font-semibold", accentClass)}>
                {value}
            </div>
            {sub && <div className="mt-1 text-xs text-gray-500">{sub}</div>}
        </div>
    );
}

function QuickLink({
    href,
    icon: Icon,
    label,
}: {
    href: string;
    icon: typeof Wallet;
    label: string;
}) {
    return (
        <Link
            href={href}
            className="flex items-center justify-between rounded border border-white/10 bg-black/20 px-3 py-2 text-gray-300 transition hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
        >
            <span className="flex items-center gap-2">
                <Icon className="h-4 w-4" />
                {label}
            </span>
            <ArrowUpRight className="h-4 w-4 opacity-60" />
        </Link>
    );
}

function PortfolioContextPanel({ summary }: { summary: PortfolioSummary }) {
    const realizedPositive = summary.realized_pnl >= 0;
    const unrealizedPositive = summary.unrealized_pnl >= 0;
    return (
        <div className="neo-card overflow-hidden">
            <header className="border-b border-white/10 px-5 py-3">
                <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                    <Wallet className="h-4 w-4 text-primary" />
                    Portfolio Context
                </h2>
            </header>
            <div className="grid gap-3 p-5 sm:grid-cols-2">
                <InfoTile label="Manual portfolios" value={String(summary.portfolio_count ?? 0)} />
                <InfoTile label="Cost basis" value={formatCurrency(summary.total_cost ?? summary.invested_value)} />
                <InfoTile
                    label="Realized P&L"
                    value={formatCurrency(summary.realized_pnl)}
                    tone={realizedPositive ? "good" : "bad"}
                />
                <InfoTile
                    label="Unrealized P&L"
                    value={formatCurrency(summary.unrealized_pnl)}
                    tone={unrealizedPositive ? "good" : "bad"}
                />
            </div>
        </div>
    );
}

function InfoTile({
    label,
    value,
    tone = "neutral",
}: {
    label: string;
    value: string;
    tone?: "neutral" | "good" | "bad";
}) {
    const toneClass = tone === "good" ? "text-accent" : tone === "bad" ? "text-secondary" : "text-gray-100";
    return (
        <div className="rounded border border-white/10 bg-black/20 p-4">
            <div className="font-mono text-[10px] uppercase tracking-widest text-gray-500">{label}</div>
            <div className={cn("mt-2 font-mono text-lg font-semibold", toneClass)}>{value}</div>
        </div>
    );
}

function RecentTradesList({ orders }: { orders: DashboardOrder[] }) {
    return (
        <div className="neo-card flex h-full flex-col overflow-hidden">
            <header className="border-b border-white/10 px-5 py-3">
                <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                    <Terminal className="h-4 w-4 text-cyan-400" />
                    Recent User Trades
                </h2>
            </header>
            <div className="flex-1 space-y-3 overflow-y-auto bg-black/40 p-4 font-mono text-xs">
                {orders.length === 0 ? (
                    <div className="flex items-center gap-2 text-gray-600">
                        <Wallet className="h-4 w-4" />
                        No recent user trades.
                    </div>
                ) : (
                    orders.map((order) => {
                        const isBuy = order.side.toLowerCase() === "buy";
                        const quantity = order.amount ?? order.quantity ?? 0;
                        const realized = order.realized_pnl;
                        return (
                            <div key={order.id} className="rounded border border-white/10 bg-white/5 px-4 py-3">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="flex min-w-0 items-center gap-2">
                                        <span
                                            className={cn(
                                                "rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest",
                                                isBuy ? "bg-green-500/10 text-green-400" : "bg-pink-500/10 text-pink-400"
                                            )}
                                        >
                                            {order.side}
                                        </span>
                                        <span className="truncate font-bold text-white">{order.symbol}</span>
                                    </div>
                                    <span className="shrink-0 text-gray-500">
                                        {order.timestamp ? new Date(order.timestamp).toLocaleDateString() : "--"}
                                    </span>
                                </div>
                                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-gray-400">
                                    <span>{order.portfolio_name || "Portfolio"}</span>
                                    <span>{quantity} @ {formatCurrency(order.price)}</span>
                                    {realized !== null && realized !== undefined ? (
                                        <span className={realized >= 0 ? "text-accent" : "text-secondary"}>
                                            Realized {formatCurrency(realized)}
                                        </span>
                                    ) : null}
                                </div>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

function EquitySpark({
    points,
    fallback,
    emptyLabel = "Waiting for cycle data...",
}: {
    points: EquityPoint[];
    fallback: PortfolioSummary;
    emptyLabel?: string;
}) {
    const w = 720;
    const h = 220;
    const pad = 24;

    const { min, max, path, areaPath, seriesEquity } = useMemo(() => {
        const series = points.length
            ? points
            : [
                  {
                      timestamp: new Date().toISOString(),
                      cash_balance: fallback.cash_balance,
                      invested_value: fallback.invested_value,
                      equity: fallback.total_equity,
                      drawdown_pct: fallback.drawdown_pct,
                  },
              ];

        const equity = series.map((p) => num(p.equity));
        const minVal = Math.min(...equity, 0);
        const maxVal = Math.max(...equity, 1);
        const range = Math.max(maxVal - minVal, 1);

        const pathStr = series
            .map((p, i) => {
                const x = pad + (i / Math.max(series.length - 1, 1)) * (w - pad * 2);
                const y = h - pad - ((num(p.equity) - minVal) / range) * (h - pad * 2);
                return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
            })
            .join(" ");

        const areaStr =
            pathStr +
            ` L ${(pad + (w - pad * 2)).toFixed(2)} ${(h - pad).toFixed(2)} L ${pad.toFixed(2)} ${(h - pad).toFixed(2)} Z`;

        return { min: minVal, max: maxVal, path: pathStr, areaPath: areaStr, seriesEquity: equity };
    }, [points, fallback]);

    return (
        <div>
            <svg viewBox={`0 0 ${w} ${h}`} className="h-56 w-full">
                <defs>
                    <linearGradient id="eq-fill" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="#00f5ff" stopOpacity="0.45" />
                        <stop offset="100%" stopColor="#00f5ff" stopOpacity="0" />
                    </linearGradient>
                </defs>
                <rect x="0" y="0" width={w} height={h} rx="8" className="fill-black/30" />
                {/* faint grid */}
                {[0.25, 0.5, 0.75].map((t) => (
                    <line
                        key={t}
                        x1={pad}
                        x2={w - pad}
                        y1={pad + t * (h - pad * 2)}
                        y2={pad + t * (h - pad * 2)}
                        className="stroke-white/5"
                        strokeWidth="1"
                    />
                ))}
                <path d={areaPath} fill="url(#eq-fill)" />
                <path
                    d={path}
                    fill="none"
                    stroke="#00f5ff"
                    strokeWidth="2.5"
                    strokeLinejoin="round"
                    style={{ filter: "drop-shadow(0 0 6px rgba(0,245,255,0.6))" }}
                />
                {points.length === 0 && (
                    <text
                        x="50%"
                        y="50%"
                        dominantBaseline="middle"
                        textAnchor="middle"
                        fill="rgba(255,255,255,0.3)"
                        className="font-mono text-sm uppercase tracking-widest"
                    >
                        {emptyLabel}
                    </text>
                )}
            </svg>
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-gray-400">
                <span>
                    <span className="mr-1 inline-block h-2 w-2 rounded-full bg-primary shadow-neon-cyan" />
                    Equity {formatCurrency(num(seriesEquity[seriesEquity.length - 1]))}
                </span>
                <span>Min {formatCurrency(min)}</span>
                <span>Max {formatCurrency(max)}</span>
            </div>
        </div>
    );
}
