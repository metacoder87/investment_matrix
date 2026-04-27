"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, TrendingUp, TrendingDown, Activity, BarChart3, Wallet, LineChart, Zap, Bot } from "lucide-react";
import CandlestickChart from "@/components/CandlestickChart";
import IndicatorPanel from "@/components/IndicatorPanel";
import SignalCard from "@/components/SignalCard";
import DeepAnalysis from "@/components/DeepAnalysis";
import { formatPrice } from "@/utils/format";
import { getApiBaseUrl } from "@/utils/api";

interface MarketTicker {
    symbol: string;
    price: number;
    size: number;
    side: string;
    ts: string;
    high_24h?: number;
    low_24h?: number;
    volume_24h?: number;
}

interface ResearchSnapshot {
    exchange: string;
    symbol: string;
    price: number | null;
    price_timestamp: string | null;
    freshness_seconds: number | null;
    row_count: number;
    data_status: {
        status: string;
        reason: string | null;
        row_count: number;
        latest_candle_at: string | null;
    };
    signal: {
        signal: string;
        confidence: number;
    } | null;
    known_limitations: string[];
}

export default function MarketPage() {
    const params = useParams<{ cId: string }>();

    // Normalize symbol (e.g., "btc-usd")
    const rawSymbol = params.cId;
    const isPair = rawSymbol.includes("-");
    const symbol = isPair ? rawSymbol.toUpperCase() : `${rawSymbol.toUpperCase()}-USD`;

    // State
    const [ticker, setTicker] = useState<MarketTicker | null>(null);
    const [snapshot, setSnapshot] = useState<ResearchSnapshot | null>(null);
    const [snapshotError, setSnapshotError] = useState<string | null>(null);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [showIndicators, setShowIndicators] = useState(true);

    // WebSocket for Live Data
    useEffect(() => {
        let cancelled = false;
        const fetchSnapshot = async () => {
            try {
                const response = await fetch(`${getApiBaseUrl()}/research/assets/auto/${encodeURIComponent(symbol)}`);
                if (!response.ok) throw new Error(`Research snapshot returned ${response.status}`);
                const data = await response.json();
                if (!cancelled) {
                    setSnapshot(data);
                    setSnapshotError(null);
                }
            } catch (err) {
                if (!cancelled) setSnapshotError(err instanceof Error ? err.message : "Research snapshot unavailable");
            }
        };
        fetchSnapshot();
        const interval = window.setInterval(fetchSnapshot, 60000);
        return () => {
            cancelled = true;
            window.clearInterval(interval);
        };
    }, [symbol]);

    useEffect(() => {
        const ws = new WebSocket("wss://ws-feed.exchange.coinbase.com");
        const cbSymbol = symbol.replace("-USDT", "-USD");

        ws.onopen = () => {
            console.log("Connected to Coinbase WS");
            ws.send(JSON.stringify({
                type: "subscribe",
                product_ids: [cbSymbol],
                channels: ["ticker"]
            }));
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "ticker") {
                setTicker({
                    symbol: symbol,
                    price: parseFloat(data.price),
                    size: parseFloat(data.last_size),
                    side: data.side,
                    ts: data.time || new Date().toISOString(),
                    high_24h: parseFloat(data.high_24h),
                    low_24h: parseFloat(data.low_24h),
                    volume_24h: parseFloat(data.volume_24h),
                });
                setLastUpdated(new Date());
            } else if (data.type === "error") {
                // Suppress alert for unsupported coins
                console.debug("Coinbase WS Error:", data.message);
            }
        };

        ws.onerror = (e) => {
            // connection errors
            console.debug("WS Connection Error (likely unsupported symbol)", e);
        };

        return () => ws.close();
    }, [symbol]);

    // Initial timestamp
    useEffect(() => {
        setLastUpdated(new Date());
    }, []);

    const displayedPrice = ticker?.price ?? snapshot?.price ?? null;
    const statusLabel = snapshot?.data_status.status?.replaceAll("_", " ") ?? "loading";

    return (
        <main className="min-h-screen bg-[#050505] p-6 text-gray-200">
            {/* Header / Nav */}
            <div className="mb-8 flex items-center justify-between">
                <Link
                    href="/market"
                    className="flex items-center gap-2 text-sm font-medium text-gray-400 hover:text-cyan-400 transition-colors"
                >
                    <ArrowLeft className="h-4 w-4" />
                    Back to Market
                </Link>
                <div className="text-xs text-gray-600 font-mono">
                    Updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : "--:--:--"}
                </div>
            </div>

            {/* Hero Section */}
            <div className="mb-8 grid grid-cols-1 gap-8 lg:grid-cols-3">
                {/* Left: Asset Info */}
                <div className="col-span-2 space-y-6">
                    <div className="flex items-end gap-4">
                        <h1 className="text-5xl font-bold tracking-tight text-white">{symbol}</h1>
                        <span className="mb-2 rounded-full border border-gray-800 bg-gray-900 px-3 py-1 text-xs font-semibold text-gray-500">
                            SPOT
                        </span>
                    </div>

                    {/* Price Display */}
                    <div className="flex items-center gap-6">
                        <div className="space-y-1">
                            <span className="text-sm text-gray-500">Current Price</span>
                            <div className="flex items-center gap-3">
                                <span className={`text-4xl font-mono font-medium ${ticker?.side === 'sell' ? 'text-pink-500' : 'text-cyan-400'}`}>
                                    {formatPrice(displayedPrice)}
                                </span>
                                {ticker && (
                                    <span className="flex items-center gap-1 rounded bg-white/5 px-2 py-0.5 text-sm">
                                        {ticker.side === 'buy' ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                                        {ticker.side === 'buy' ? 'Buy' : 'Sell'}
                                    </span>
                                )}
                            </div>
                        </div>

                        {/* Stats Grid */}
                        <div className="hidden h-12 w-px bg-white/10 sm:block" />
                        <div className="grid grid-cols-3 gap-6">
                            <div>
                                <span className="block text-xs text-gray-500">24h High</span>
                                <span className="font-mono text-lg text-green-400">
                                    ${ticker?.high_24h?.toLocaleString() || "---"}
                                </span>
                            </div>
                            <div>
                                <span className="block text-xs text-gray-500">24h Low</span>
                                <span className="font-mono text-lg text-red-400">
                                    ${ticker?.low_24h?.toLocaleString() || "---"}
                                </span>
                            </div>
                            <div>
                                <span className="block text-xs text-gray-500">24h Volume</span>
                                <span className="font-mono text-lg text-gray-300">
                                    {ticker?.volume_24h?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "---"}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right: Actions */}
                <div className="flex flex-col justify-center gap-4 rounded-2xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-sm">
                    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                        <div className="text-xs uppercase tracking-wide text-gray-500">Research status</div>
                        <div className="mt-1 text-sm font-semibold capitalize text-white">{statusLabel}</div>
                        <div className="mt-1 text-xs text-gray-500">
                            {snapshot ? `${snapshot.exchange.toUpperCase()} · ${snapshot.row_count} candles` : snapshotError || "Loading snapshot..."}
                        </div>
                        {snapshot?.data_status.reason && (
                            <div className="mt-2 text-xs text-yellow-300">{snapshot.data_status.reason}</div>
                        )}
                    </div>
                    <Link
                        href={`/paper?symbol=${encodeURIComponent(symbol)}`}
                        className="flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-500 py-3 font-semibold text-black shadow-[0_0_20px_rgba(34,211,238,0.3)] transition-all hover:bg-cyan-400"
                    >
                        <Wallet className="h-4 w-4" />
                        Paper Trade {symbol.split("-")[0]}
                    </Link>
                    <Link
                        href={`/crew?symbol=${encodeURIComponent(symbol)}`}
                        className="flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/10 py-3 font-semibold text-cyan-100 transition-all hover:bg-cyan-500/20"
                    >
                        <Bot className="h-4 w-4" />
                        Analyze with Crew
                    </Link>
                    <button
                        onClick={() => setShowIndicators(!showIndicators)}
                        className={`flex w-full items-center justify-center gap-2 rounded-lg border py-3 font-semibold transition-all ${showIndicators
                            ? "border-purple-500/50 bg-purple-500/10 text-purple-400"
                            : "border-white/10 bg-transparent text-white hover:bg-white/5"
                            }`}
                    >
                        <LineChart className="h-4 w-4" />
                        {showIndicators ? "Hide Indicators" : "Show Indicators"}
                    </button>
                </div>
            </div>

            {/* Chart Section - Main Feature */}
            <div className="mb-8 space-y-4">
                <div className="flex items-center gap-2">
                    <Activity className="h-5 w-5 text-cyan-400" />
                    <h2 className="text-xl font-semibold text-white">Price Chart</h2>
                </div>

                {/* Candlestick Chart Component */}
                <CandlestickChart symbol={symbol} exchange="auto" />
                {snapshot?.known_limitations?.length ? (
                    <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/10 p-3 text-sm text-yellow-100">
                        {snapshot.known_limitations[0]}
                    </div>
                ) : null}
            </div>

            {/* Technical Indicators */}
            {showIndicators && (
                <div className="mb-8">
                    <div className="mb-4 flex items-center gap-2">
                        <BarChart3 className="h-5 w-5 text-purple-400" />
                        <h2 className="text-xl font-semibold text-white">Technical Indicators</h2>
                    </div>
                    <IndicatorPanel symbol={symbol} />
                </div>
            )}

            {/* Deep Analysis Section */}
            <div className="mb-8">
                <DeepAnalysis symbol={symbol} />
            </div>

            {/* Bottom Grid: Stats & Info */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6">
                    <h3 className="mb-4 flex items-center gap-2 text-lg font-medium text-white">
                        <BarChart3 className="h-5 w-5 text-purple-400" />
                        Market Stats
                    </h3>
                    <div className="space-y-4">
                        <div className="flex justify-between border-b border-white/5 pb-2">
                            <span className="text-gray-500">24h High</span>
                            <span className="font-mono text-green-400">
                                ${ticker?.high_24h?.toLocaleString() || "---"}
                            </span>
                        </div>
                        <div className="flex justify-between border-b border-white/5 pb-2">
                            <span className="text-gray-500">24h Low</span>
                            <span className="font-mono text-red-400">
                                ${ticker?.low_24h?.toLocaleString() || "---"}
                            </span>
                        </div>
                        <div className="flex justify-between border-b border-white/5 pb-2">
                            <span className="text-gray-500">24h Volume</span>
                            <span className="font-mono text-gray-300">
                                {ticker?.volume_24h?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "---"}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-500">Last Trade Size</span>
                            <span className="font-mono text-gray-300">{ticker?.size || "---"}</span>
                        </div>
                    </div>
                </div>

                <div>
                    <h3 className="mb-4 flex items-center gap-2 text-lg font-medium text-white">
                        <Zap className="h-5 w-5 text-yellow-400" />
                        Trading Signal
                    </h3>
                    <SignalCard symbol={symbol} />
                </div>
            </div>
        </main>
    );
}
