"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, TrendingUp, TrendingDown, Activity, BarChart3, Wallet, LineChart, Zap } from "lucide-react";
import CandlestickChart from "@/components/CandlestickChart";
import IndicatorPanel from "@/components/IndicatorPanel";
import SignalCard from "@/components/SignalCard";
import DeepAnalysis from "@/components/DeepAnalysis";

interface MarketPageProps {
    params: {
        cId: string;
    };
}

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

export default function MarketPage({ params }: MarketPageProps) {
    // Normalize symbol (e.g., "btc-usd")
    const rawSymbol = params.cId;
    const isPair = rawSymbol.includes("-");
    const symbol = isPair ? rawSymbol.toUpperCase() : `${rawSymbol.toUpperCase()}-USD`;

    // State
    const [ticker, setTicker] = useState<MarketTicker | null>(null);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [showIndicators, setShowIndicators] = useState(true);

    // WebSocket for Live Data
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
            }
        };

        return () => ws.close();
    }, [symbol]);

    // Initial timestamp
    useEffect(() => {
        setLastUpdated(new Date());
    }, []);

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
                                <span className={`text-4xl font-mono font-medium ${ticker?.side === 'buy' ? 'text-cyan-400' : 'text-pink-500'}`}>
                                    ${ticker?.price?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || "---"}
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
                    <button className="flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-500 py-3 font-semibold text-black hover:bg-cyan-400 transition-all shadow-[0_0_20px_rgba(34,211,238,0.3)]">
                        <Wallet className="h-4 w-4" />
                        Trade {symbol.split("-")[0]}
                    </button>
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
                <CandlestickChart symbol={symbol} exchange="coinbase" />
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
