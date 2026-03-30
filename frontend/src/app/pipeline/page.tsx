"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Database, RefreshCw, AlertTriangle } from "lucide-react";
import { getApiBaseUrl } from "@/utils/api";

type ImportCounts = Record<string, number>;

interface IngestionSymbolHealth {
    symbol: string;
    latest_stream_timestamp: string | null;
    latest_db_timestamp: string | null;
    stream_lag_seconds: number | null;
    db_lag_seconds: number | null;
    source: string | null;
}

interface IngestionHealthResponse {
    checked_at: string;
    exchange: string;
    redis_ok: boolean;
    symbols: IngestionSymbolHealth[];
    imports: {
        lookback_hours: number;
        counts: ImportCounts;
    };
}

interface CoverageResponse {
    trades: number;
    first_timestamp: string | null;
    last_timestamp: string | null;
    source?: string;
}

interface GapResponse {
    missing_buckets: number;
    total_buckets: number;
    gaps: { start: string; end: string; buckets: number }[];
}

const DEFAULT_SYMBOLS = "BTC-USD,ETH-USD,SOL-USD";

function formatLag(seconds: number | null | undefined) {
    if (seconds === null || seconds === undefined) return "—";
    if (seconds < 1) return "<1s";
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}m`;
}

function averageLag(values: (number | null)[]) {
    const filtered = values.filter((v) => typeof v === "number") as number[];
    if (!filtered.length) return null;
    const sum = filtered.reduce((acc, val) => acc + val, 0);
    return sum / filtered.length;
}

export default function PipelineHealthPage() {
    const [exchange, setExchange] = useState("coinbase");
    const [symbols, setSymbols] = useState(DEFAULT_SYMBOLS);
    const [rangeHours, setRangeHours] = useState(1);
    const [bucketSeconds, setBucketSeconds] = useState(60);
    const [health, setHealth] = useState<IngestionHealthResponse | null>(null);
    const [coverageMap, setCoverageMap] = useState<Record<string, CoverageResponse>>({});
    const [gapMap, setGapMap] = useState<Record<string, GapResponse>>({});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const symbolList = useMemo(
        () => symbols.split(",").map((s) => s.trim()).filter(Boolean),
        [symbols]
    );

    const fetchAll = async () => {
        setLoading(true);
        setError(null);
        const baseUrl = getApiBaseUrl();
        try {
            const healthRes = await fetch(
                `${baseUrl}/system/ingestion/health?exchange=${encodeURIComponent(exchange)}&symbols=${encodeURIComponent(symbols)}&lookback_hours=24`
            );
            if (!healthRes.ok) throw new Error("Failed to load ingestion health");
            const healthPayload: IngestionHealthResponse = await healthRes.json();
            setHealth(healthPayload);

            const now = new Date();
            const start = new Date(now.getTime() - rangeHours * 60 * 60 * 1000);

            const coverageEntries = await Promise.all(
                symbolList.map(async (sym) => {
                    const res = await fetch(`${baseUrl}/market/coverage/${exchange}/${sym}`);
                    if (!res.ok) return [sym, null] as const;
                    return [sym, (await res.json()) as CoverageResponse] as const;
                })
            );

            const gapEntries = await Promise.all(
                symbolList.map(async (sym) => {
                    const res = await fetch(
                        `${baseUrl}/market/gaps/${exchange}/${sym}?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(now.toISOString())}&bucket_seconds=${bucketSeconds}&max_points=5000`
                    );
                    if (!res.ok) return [sym, null] as const;
                    return [sym, (await res.json()) as GapResponse] as const;
                })
            );

            setCoverageMap(Object.fromEntries(coverageEntries.filter(([, v]) => v)) as Record<string, CoverageResponse>);
            setGapMap(Object.fromEntries(gapEntries.filter(([, v]) => v)) as Record<string, GapResponse>);
        } catch (err) {
            console.error(err);
            setError("Unable to load pipeline health. Check API connectivity.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [exchange, symbols, rangeHours, bucketSeconds]);

    const streamAvg = averageLag(health?.symbols.map((s) => s.stream_lag_seconds) || []);
    const dbAvg = averageLag(health?.symbols.map((s) => s.db_lag_seconds) || []);
    const importCounts = health?.imports.counts || {};

    return (
        <main className="p-8 max-w-7xl mx-auto space-y-8">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-white">Pipeline Health</h1>
                    <p className="text-sm text-gray-400 mt-2">
                        Live coverage, gap detection, and ingestion latency for critical trading pairs.
                    </p>
                </div>
                <button
                    onClick={fetchAll}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-white/10 bg-white/5 text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
                >
                    <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                    Refresh
                </button>
            </div>

            <section className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm space-y-4">
                <div className="flex flex-wrap gap-4">
                    <div className="flex flex-col gap-2">
                        <label className="text-xs text-gray-400">Exchange</label>
                        <select
                            value={exchange}
                            onChange={(e) => setExchange(e.target.value)}
                            className="bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white"
                        >
                            <option value="coinbase">Coinbase</option>
                            <option value="binance">Binance</option>
                            <option value="kraken">Kraken</option>
                        </select>
                    </div>
                    <div className="flex flex-col gap-2 min-w-[280px]">
                        <label className="text-xs text-gray-400">Symbols</label>
                        <input
                            value={symbols}
                            onChange={(e) => setSymbols(e.target.value.toUpperCase())}
                            className="bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div className="flex flex-col gap-2">
                        <label className="text-xs text-gray-400">Gap Window</label>
                        <select
                            value={rangeHours}
                            onChange={(e) => setRangeHours(parseInt(e.target.value, 10))}
                            className="bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white"
                        >
                            <option value={1}>Last 1h</option>
                            <option value={6}>Last 6h</option>
                            <option value={24}>Last 24h</option>
                        </select>
                    </div>
                    <div className="flex flex-col gap-2">
                        <label className="text-xs text-gray-400">Bucket</label>
                        <select
                            value={bucketSeconds}
                            onChange={(e) => setBucketSeconds(parseInt(e.target.value, 10))}
                            className="bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white"
                        >
                            <option value={1}>1s</option>
                            <option value={5}>5s</option>
                            <option value={60}>60s</option>
                            <option value={300}>5m</option>
                        </select>
                    </div>
                </div>
            </section>

            {error && (
                <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
                    {error}
                </div>
            )}

            <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="rounded-xl border border-white/10 bg-surface/60 p-6 backdrop-blur-sm space-y-3">
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-400">Streaming Health</span>
                        <Activity className="h-4 w-4 text-primary" />
                    </div>
                    <div className="text-2xl font-bold text-white">{formatLag(streamAvg)}</div>
                    <div className="text-xs text-gray-400">
                        Avg stream lag · Redis {health?.redis_ok ? "online" : "offline"}
                    </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-surface/60 p-6 backdrop-blur-sm space-y-3">
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-400">Persistence Lag</span>
                        <Database className="h-4 w-4 text-primary" />
                    </div>
                    <div className="text-2xl font-bold text-white">{formatLag(dbAvg)}</div>
                    <div className="text-xs text-gray-400">Avg time since DB write</div>
                </div>
                <div className="rounded-xl border border-white/10 bg-surface/60 p-6 backdrop-blur-sm space-y-3">
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-400">Import Activity</span>
                        <AlertTriangle className="h-4 w-4 text-primary" />
                    </div>
                    <div className="flex items-center gap-4 text-sm">
                        <div className="text-green-400 font-semibold">Success {importCounts.success || 0}</div>
                        <div className="text-yellow-400 font-semibold">Running {importCounts.started || 0}</div>
                        <div className="text-red-400 font-semibold">Failed {importCounts.failed || 0}</div>
                    </div>
                    <div className="text-xs text-gray-400">Last 24h import runs</div>
                </div>
            </section>

            <section className="rounded-xl border border-white/10 bg-surface/60 overflow-hidden">
                <div className="p-4 border-b border-white/10 bg-white/5 flex items-center justify-between">
                    <h2 className="font-semibold text-gray-200">Symbol Reliability Matrix</h2>
                    <span className="text-xs text-gray-500">Updated {health?.checked_at ? new Date(health.checked_at).toLocaleTimeString() : "—"}</span>
                </div>
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="text-xs text-gray-500 border-b border-white/5">
                            <th className="p-4 font-medium">Symbol</th>
                            <th className="p-4 font-medium">Stream Lag</th>
                            <th className="p-4 font-medium">DB Lag</th>
                            <th className="p-4 font-medium">Coverage</th>
                            <th className="p-4 font-medium">Last DB Tick</th>
                            <th className="p-4 font-medium">Gaps</th>
                        </tr>
                    </thead>
                    <tbody>
                        {symbolList.map((sym) => {
                            const entry = health?.symbols.find((s) => s.symbol === sym);
                            const coverage = coverageMap[sym];
                            const gaps = gapMap[sym];
                            const lagClass = (lag?: number | null) =>
                                lag && lag > 120 ? "text-red-400" : lag && lag > 30 ? "text-yellow-400" : "text-green-400";

                            return (
                                <tr key={sym} className="border-b border-white/5 hover:bg-white/[0.02]">
                                    <td className="p-4 font-bold text-white">{sym}</td>
                                    <td className={`p-4 font-mono ${lagClass(entry?.stream_lag_seconds)}`}>
                                        {formatLag(entry?.stream_lag_seconds)}
                                    </td>
                                    <td className={`p-4 font-mono ${lagClass(entry?.db_lag_seconds)}`}>
                                        {formatLag(entry?.db_lag_seconds)}
                                    </td>
                                    <td className="p-4 text-gray-300">
                                        {coverage ? `${coverage.trades.toLocaleString()} (${coverage.source || "n/a"})` : "—"}
                                    </td>
                                    <td className="p-4 text-gray-400 text-xs">
                                        {coverage?.last_timestamp ? new Date(coverage.last_timestamp).toLocaleString() : "—"}
                                    </td>
                                    <td className="p-4 text-gray-300">
                                        {gaps ? `${gaps.missing_buckets}/${gaps.total_buckets}` : "—"}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </section>
        </main>
    );
}
