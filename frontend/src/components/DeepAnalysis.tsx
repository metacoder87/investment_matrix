"use client";

import { useEffect, useState } from "react";
import { Activity, Brain, TrendingUp, AlertTriangle } from "lucide-react";

interface QuantMetrics {
    annualized_volatility: number;
    sharpe_ratio: number;
    max_drawdown: number;
    sortino_ratio: number;
}

interface Fundamentals {
    market_cap: number;
    fully_diluted_valuation: number;
    total_supply: number;
    circulating_supply: number;
    ath: number;
    atl: number;
}

interface SentimentData {
    fear_and_greed: {
        value: number;
        value_classification: string;
    } | null;
}

interface DeepAnalysisProps {
    symbol: string;
}

export default function DeepAnalysis({ symbol }: DeepAnalysisProps) {
    const [quant, setQuant] = useState<QuantMetrics | null>(null);
    const [fund, setFund] = useState<Fundamentals | null>(null);
    const [sentiment, setSentiment] = useState<SentimentData | null>(null);
    const [loading, setLoading] = useState(true);

    const baseSymbol = symbol.split("-")[0]; // e.g., BTC from BTC-USD

    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            try {
                // Fetch Quant
                const quantRes = await fetch(`http://localhost:8000/api/coin/${symbol}/quant`);
                if (quantRes.ok) setQuant(await quantRes.json());

                // Fetch Fundamentals (using base symbol)
                const fundRes = await fetch(`http://localhost:8000/api/coin/${baseSymbol}/fundamentals`);
                if (fundRes.ok) setFund(await fundRes.json());

                // Fetch Sentiment
                const sentRes = await fetch(`http://localhost:8000/api/coin/${baseSymbol}/sentiment`);
                if (sentRes.ok) setSentiment(await sentRes.json());

            } catch (e) {
                console.error("Analysis fetch error", e);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [symbol, baseSymbol]);

    if (loading) return <div className="text-gray-500 animate-pulse">Loading deep analysis...</div>;

    return (
        <div className="space-y-6">
            <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                <Brain className="h-6 w-6 text-pink-500" />
                Deep Market Analysis
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* 1. Quantitative Risk Card */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-sm">
                    <h3 className="mb-4 flex items-center gap-2 text-lg font-medium text-cyan-400">
                        <Activity className="h-5 w-5" />
                        Risk Metrics (1Y)
                    </h3>
                    <div className="space-y-4">
                        <div className="flex justify-between">
                            <span className="text-gray-400">Volatility (Ann.)</span>
                            <span className="font-mono text-white">{(quant?.annualized_volatility ?? 0 * 100).toFixed(2)}%</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-400">Sharpe Ratio</span>
                            <span className={`font-mono ${(quant?.sharpe_ratio ?? 0) > 1 ? "text-green-400" : "text-yellow-400"}`}>
                                {quant?.sharpe_ratio?.toFixed(2) ?? "---"}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-400">Sortino Ratio</span>
                            <span className="font-mono text-white">{quant?.sortino_ratio?.toFixed(2) ?? "---"}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-400">Max Drawdown</span>
                            <span className="font-mono text-red-400">{((quant?.max_drawdown ?? 0) * 100).toFixed(2)}%</span>
                        </div>
                    </div>
                </div>

                {/* 2. Fundamentals Card */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-sm">
                    <h3 className="mb-4 flex items-center gap-2 text-lg font-medium text-purple-400">
                        <TrendingUp className="h-5 w-5" />
                        Fundamentals
                    </h3>
                    <div className="space-y-4">
                        <div className="flex justify-between">
                            <span className="text-gray-400">Market Cap</span>
                            <span className="font-mono text-white">${fund?.market_cap?.toLocaleString() ?? "---"}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-400">FDV</span>
                            <span className="font-mono text-white">${fund?.fully_diluted_valuation?.toLocaleString() ?? "---"}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-400">Circulating Supply</span>
                            <span className="font-mono text-white">{fund?.circulating_supply?.toLocaleString() ?? "---"}</span>
                        </div>
                        <div className="flex justify-between border-t border-white/5 pt-2">
                            <span className="text-gray-400">All Time High</span>
                            <div className="text-right">
                                <div className="font-mono text-white">${fund?.ath?.toLocaleString()}</div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* 3. Sentiment & Fear/Greed */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-sm">
                    <h3 className="mb-4 flex items-center gap-2 text-lg font-medium text-yellow-400">
                        <AlertTriangle className="h-5 w-5" />
                        Market Sentiment
                    </h3>

                    <div className="flex flex-col items-center justify-center py-4">
                        {sentiment?.fear_and_greed ? (
                            <>
                                <div className="text-5xl font-bold text-white mb-2">{sentiment.fear_and_greed.value}</div>
                                <div className={`px-3 py-1 rounded-full text-sm font-bold ${sentiment.fear_and_greed.value < 25 ? "bg-red-500/20 text-red-500" :
                                        sentiment.fear_and_greed.value > 75 ? "bg-green-500/20 text-green-500" :
                                            "bg-yellow-500/20 text-yellow-500"
                                    }`}>
                                    {sentiment.fear_and_greed.value_classification}
                                </div>
                            </>
                        ) : (
                            <span className="text-gray-500">Unavailable</span>
                        )}
                        <span className="mt-4 text-xs text-gray-500">Crypto Fear & Greed Index</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
