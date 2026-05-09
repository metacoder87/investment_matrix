"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
    Activity,
    AlertTriangle,
    ArrowUpRight,
    Bot,
    CirclePause,
    Layers,
    LineChart as LineChartIcon,
    PercentCircle,
    Play,
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
} from "@/types/dashboard";

/* ---------- Types (mirrors crew/summary endpoint) ---------- */



const emptySummary: PortfolioSummary = {
    available_bankroll: 0,
    cash_balance: 0,
    invested_value: 0,
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
        .then((r) => (r.ok ? (r.json() as Promise<T>) : null))
        .catch(() => null);
}

/* ---------- Dashboard ---------- */

export default function DashboardPage() {
    const [summary, setSummary] = useState<PortfolioSummary>(emptySummary);
    const [equity, setEquity] = useState<EquityPoint[]>([]);
    const [positions, setPositions] = useState<Position[]>([]);
    const [theses, setTheses] = useState<ThesisLite[]>([]);
    const [activity, setActivity] = useState<TraceEventLite[]>([]);
    const [botState, setBotState] = useState<string>("unknown");
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        const base = getApiBaseUrl();
        const [s, e, p, t, a] = await Promise.all([
            safeFetch<Record<string, unknown>>(`${base}/crew/summary`),
            safeFetch<EquityPoint[]>(`${base}/crew/portfolio/equity`),
            safeFetch<Position[]>(`${base}/crew/portfolio/positions`),
            safeFetch<ThesisLite[]>(`${base}/crew/theses`),
            safeFetch<TraceEventLite[]>(`${base}/crew/activity?limit=5&debug=false`),
        ]);
        return { s, e, p, t, a };
    }, []);

    useEffect(() => {
        let alive = true;
        const refresh = async () => {
            const { s, e, p, t, a } = await load();
            if (!alive) return;
            if (s) {
                const sleeve = (s.sleeve_win_rates ?? {}) as Record<string, unknown>;
                setSummary({
                    available_bankroll: num(s.available_bankroll),
                    cash_balance: num(s.cash_balance),
                    invested_value: num(s.invested_value),
                    total_equity: num(s.total_equity),
                    long_exposure: num(s.long_exposure),
                    short_exposure: num(s.short_exposure),
                    realized_pnl: num(s.realized_pnl),
                    unrealized_pnl: num(s.unrealized_pnl),
                    all_time_pnl: num(s.all_time_pnl),
                    current_cycle_pnl: num(s.current_cycle_pnl),
                    drawdown_pct: num(s.drawdown_pct),
                    exposure_pct: num(s.exposure_pct),
                    open_positions: num(s.open_positions),
                    sleeve_win_rates: {
                        long: num(sleeve.long),
                        short: num(sleeve.short),
                    },
                });
            }
            if (Array.isArray(e)) setEquity(e);
            if (Array.isArray(p)) setPositions(p);
            if (Array.isArray(t)) setTheses(t);
            if (Array.isArray(a)) setActivity(a);
            setLoading(false);
        };
        refresh();
        const id = window.setInterval(refresh, 30_000);
        return () => {
            alive = false;
            window.clearInterval(id);
        };
    }, [load]);

    const winRate = useMemo(() => {
        const long = summary.sleeve_win_rates.long;
        const short = summary.sleeve_win_rates.short;
        const avg = ((long || 0) + (short || 0)) / (long && short ? 2 : long || short ? 1 : 1);
        return Number.isFinite(avg) ? avg * 100 : 0;
    }, [summary]);

    const pnlPositive = summary.current_cycle_pnl >= 0;
    const hasOpenPositions = summary.open_positions > 0;

    return (
        <div className="mx-auto max-w-[1600px] space-y-6 p-4 md:p-8">
            {/* Header */}
            <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div>
                    <h1 className="font-mono text-3xl font-semibold uppercase tracking-wider text-white neon-text">
                        Command Deck
                    </h1>
                    <p className="mt-1 text-sm text-gray-400">
                        High-level KPIs from the AI crew. For dense market data, head to{" "}
                        <Link href="/market" className="text-primary hover:underline">
                            Market <ArrowUpRight className="-mt-0.5 inline h-3.5 w-3.5" />
                        </Link>
                        .
                    </p>
                </div>
                <div className="rounded border border-primary/20 bg-primary/5 px-3 py-2 font-mono text-xs text-primary">
                    CryptoInsight Terminal v1.0.0 — {loading ? "syncing…" : "live"}
                </div>
            </div>

            {/* KPI grid */}
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <KpiCard
                    icon={Wallet}
                    label="Bankroll"
                    value={formatCurrency(summary.available_bankroll)}
                    sub={`Equity ${formatCurrency(summary.total_equity)}`}
                    accent="cyan"
                />
                <KpiCard
                    icon={PercentCircle}
                    label="Win Rate"
                    value={`${winRate.toFixed(1)}%`}
                    sub={`L ${(summary.sleeve_win_rates.long * 100).toFixed(0)}% / S ${(summary.sleeve_win_rates.short * 100).toFixed(0)}%`}
                    accent="green"
                />
                <KpiCard
                    icon={Target}
                    label="Open Positions"
                    value={String(summary.open_positions)}
                    sub={`Exposure ${summary.exposure_pct.toFixed(1)}%`}
                    accent={hasOpenPositions ? "pulse" : "cyan"}
                />
                <KpiCard
                    icon={pnlPositive ? Activity : AlertTriangle}
                    label="Cycle P&L"
                    value={formatCurrency(summary.current_cycle_pnl)}
                    sub={`Drawdown ${summary.drawdown_pct.toFixed(2)}%`}
                    accent={pnlPositive ? "green" : "pink"}
                />
            </section>

            {/* Chart + secondary */}
            <section className="grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
                <div className="neo-card kpi-shimmer">
                    <header className="flex items-center justify-between border-b border-white/10 px-5 py-3">
                        <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                            <LineChartIcon className="h-4 w-4 text-primary" />
                            Equity Curve
                        </h2>
                        <span className="font-mono text-[11px] text-gray-500">
                            {equity.length} pts
                        </span>
                    </header>
                    <div className="p-5">
                        <EquitySpark points={equity} fallback={summary} />
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
                <div className="flex flex-col gap-4">
                    <PositionsTable positions={positions} />
                    <ThesesList theses={theses} />
                </div>
                <div className="h-[600px] xl:h-auto">
                    <ActivityFeed activity={activity} />
                </div>
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

function EquitySpark({
    points,
    fallback,
}: {
    points: EquityPoint[];
    fallback: PortfolioSummary;
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
                        Waiting for cycle data...
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
