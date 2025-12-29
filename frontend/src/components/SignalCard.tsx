"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus, AlertTriangle, Target, ShieldAlert } from "lucide-react";

interface SignalData {
    symbol: string;
    signal: string;
    confidence: number;
    price: number;
    timestamp: string;
    reasons: string[];
    indicators: Record<string, number>;
    risk_reward: number | null;
    target_price: number | null;
    stop_loss: number | null;
}

interface SignalCardProps {
    symbol: string;
    onSignalLoad?: (signal: SignalData | null) => void;
}

export default function SignalCard({ symbol, onSignalLoad }: SignalCardProps) {
    const [signal, setSignal] = useState<SignalData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const normalizedSymbol = symbol.toUpperCase().replace("/", "-");

    useEffect(() => {
        const fetchSignal = async () => {
            setLoading(true);
            setError(null);
            try {
                const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
                const response = await fetch(`${baseUrl}/signals/${normalizedSymbol}`);

                if (!response.ok) {
                    if (response.status === 404) {
                        setError("Insufficient historical data. Trigger a backfill first.");
                    } else {
                        throw new Error(`Failed to fetch: ${response.status}`);
                    }
                    setLoading(false);
                    return;
                }

                const data = await response.json();
                setSignal(data);
                onSignalLoad?.(data);
                setLoading(false);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to load signal");
                setLoading(false);
            }
        };

        fetchSignal();
        // Refresh every 60s
        const interval = setInterval(fetchSignal, 60000);
        return () => clearInterval(interval);
    }, [normalizedSymbol, onSignalLoad]);

    const getSignalColor = (signal: string) => {
        switch (signal) {
            case "strong_buy": return "text-emerald-400";
            case "buy": return "text-green-400";
            case "hold": return "text-yellow-400";
            case "sell": return "text-orange-400";
            case "strong_sell": return "text-red-400";
            default: return "text-gray-400";
        }
    };

    const getSignalBgColor = (signal: string) => {
        switch (signal) {
            case "strong_buy": return "bg-emerald-500/20 border-emerald-500/30";
            case "buy": return "bg-green-500/20 border-green-500/30";
            case "hold": return "bg-yellow-500/20 border-yellow-500/30";
            case "sell": return "bg-orange-500/20 border-orange-500/30";
            case "strong_sell": return "bg-red-500/20 border-red-500/30";
            default: return "bg-gray-500/20 border-gray-500/30";
        }
    };

    const getSignalIcon = (signal: string) => {
        switch (signal) {
            case "strong_buy":
            case "buy":
                return <TrendingUp className="h-6 w-6" />;
            case "sell":
            case "strong_sell":
                return <TrendingDown className="h-6 w-6" />;
            default:
                return <Minus className="h-6 w-6" />;
        }
    };

    const getSignalLabel = (signal: string) => {
        switch (signal) {
            case "strong_buy": return "STRONG BUY";
            case "buy": return "BUY";
            case "hold": return "HOLD";
            case "sell": return "SELL";
            case "strong_sell": return "STRONG SELL";
            default: return signal.toUpperCase();
        }
    };

    if (loading) {
        return (
            <div className="animate-pulse rounded-xl border border-white/10 bg-white/[0.02] p-6">
                <div className="h-8 w-32 rounded bg-white/10 mb-4" />
                <div className="h-4 w-full rounded bg-white/10 mb-2" />
                <div className="h-4 w-3/4 rounded bg-white/10" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 p-6">
                <div className="flex items-center gap-2 text-yellow-400 mb-2">
                    <AlertTriangle className="h-5 w-5" />
                    <span className="font-medium">Signal Unavailable</span>
                </div>
                <p className="text-sm text-yellow-400/70">{error}</p>
            </div>
        );
    }

    if (!signal) return null;

    return (
        <div className={`rounded-xl border p-6 ${getSignalBgColor(signal.signal)}`}>
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className={getSignalColor(signal.signal)}>
                        {getSignalIcon(signal.signal)}
                    </div>
                    <div>
                        <div className={`text-2xl font-bold ${getSignalColor(signal.signal)}`}>
                            {getSignalLabel(signal.signal)}
                        </div>
                        <div className="text-xs text-gray-500">
                            {new Date(signal.timestamp).toLocaleString()}
                        </div>
                    </div>
                </div>
                <div className="text-right">
                    <div className="text-sm text-gray-400">Confidence</div>
                    <div className={`text-2xl font-mono font-bold ${getSignalColor(signal.signal)}`}>
                        {(signal.confidence * 100).toFixed(0)}%
                    </div>
                </div>
            </div>

            {/* Reasons */}
            <div className="mb-4">
                <div className="text-xs text-gray-500 mb-2">Analysis Summary</div>
                <ul className="space-y-1">
                    {signal.reasons.map((reason, idx) => (
                        <li key={idx} className="text-sm text-gray-300 flex items-start gap-2">
                            <span className={`mt-1.5 h-1.5 w-1.5 rounded-full ${getSignalColor(signal.signal).replace('text-', 'bg-')}`} />
                            {reason}
                        </li>
                    ))}
                </ul>
            </div>

            {/* Target & Stop */}
            {(signal.target_price || signal.stop_loss) && (
                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-white/10">
                    {signal.target_price && (
                        <div>
                            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                                <Target className="h-3 w-3" />
                                Target Price
                            </div>
                            <div className="font-mono text-lg text-green-400">
                                ${signal.target_price.toLocaleString()}
                            </div>
                        </div>
                    )}
                    {signal.stop_loss && (
                        <div>
                            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                                <ShieldAlert className="h-3 w-3" />
                                Stop Loss
                            </div>
                            <div className="font-mono text-lg text-red-400">
                                ${signal.stop_loss.toLocaleString()}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Risk/Reward */}
            {signal.risk_reward && (
                <div className="mt-4 pt-4 border-t border-white/10 flex items-center justify-between">
                    <span className="text-xs text-gray-500">Risk/Reward Ratio</span>
                    <span className="font-mono text-cyan-400">1:{signal.risk_reward}</span>
                </div>
            )}

            {/* Key Indicators */}
            <div className="mt-4 pt-4 border-t border-white/10">
                <div className="text-xs text-gray-500 mb-2">Key Indicators</div>
                <div className="flex flex-wrap gap-2">
                    {signal.indicators.rsi != null && (
                        <span className={`px-2 py-1 rounded text-xs font-mono ${signal.indicators.rsi >= 70 ? 'bg-red-500/20 text-red-400' :
                                signal.indicators.rsi <= 30 ? 'bg-green-500/20 text-green-400' :
                                    'bg-white/10 text-gray-400'
                            }`}>
                            RSI: {signal.indicators.rsi.toFixed(1)}
                        </span>
                    )}
                    {signal.indicators.macd != null && (
                        <span className={`px-2 py-1 rounded text-xs font-mono ${signal.indicators.macd > 0 ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                            }`}>
                            MACD: {signal.indicators.macd.toFixed(2)}
                        </span>
                    )}
                    {signal.indicators.atr != null && (
                        <span className="px-2 py-1 rounded bg-white/10 text-xs font-mono text-gray-400">
                            ATR: {signal.indicators.atr.toFixed(2)}
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
}
