"use client";

import { useMemo, useState } from "react";
import { FlaskConical, TrendingUp, BarChart3 } from "lucide-react";
import MarketChart from "@/components/MarketChart";
import { getApiBaseUrl } from "@/utils/api";

type BacktestMetrics = Record<string, unknown>;

interface BacktestResponse {
    run_id: number;
    metrics: BacktestMetrics;
    trades?: Array<Record<string, any>>;
    equity_curve?: Array<{ timestamp: string; equity: number }>;
    source: string;
    requested_bucket_seconds: number;
    bucket_seconds: number;
}

interface WalkForwardResponse {
    report_id?: number | null;
    summary: Record<string, any>;
    windows: Array<Record<string, any>>;
}

const formatInputDate = (value: Date) => {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(
        value.getHours()
    )}:${pad(value.getMinutes())}`;
};

export default function BacktestsPage() {
    const now = new Date();
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

    const [symbol, setSymbol] = useState("BTC-USD");
    const [exchange, setExchange] = useState("coinbase");
    const [timeframe, setTimeframe] = useState("1m");
    const [start, setStart] = useState(formatInputDate(weekAgo));
    const [end, setEnd] = useState(formatInputDate(now));
    const [strategy, setStrategy] = useState("sma_cross");
    const [strategyParams, setStrategyParams] = useState('{"short_window": 20, "long_window": 50}');
    const [initialCash, setInitialCash] = useState(10000);
    const [feeRate, setFeeRate] = useState(0.001);
    const [slippageBps, setSlippageBps] = useState(5);
    const [maxPositionPct, setMaxPositionPct] = useState(1.0);

    const [backtestResult, setBacktestResult] = useState<BacktestResponse | null>(null);
    const [walkForwardResult, setWalkForwardResult] = useState<WalkForwardResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const [trainWindow, setTrainWindow] = useState(300);
    const [testWindow, setTestWindow] = useState(100);
    const [stepWindow, setStepWindow] = useState(100);

    const equitySeries = useMemo(() => {
        if (!backtestResult?.equity_curve) return [];
        return backtestResult.equity_curve.map((point) => ({
            time: point.timestamp,
            value: point.equity,
        }));
    }, [backtestResult]);

    const runBacktest = async () => {
        setLoading(true);
        setError(null);
        try {
            const baseUrl = getApiBaseUrl();
            const params = strategyParams ? JSON.parse(strategyParams) : {};
            const response = await fetch(`${baseUrl}/backtests`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    symbol,
                    exchange,
                    start: new Date(start).toISOString(),
                    end: new Date(end).toISOString(),
                    timeframe,
                    source: "auto",
                    strategy,
                    strategy_params: params,
                    initial_cash: initialCash,
                    fee_rate: feeRate,
                    slippage_bps: slippageBps,
                    max_position_pct: maxPositionPct,
                    include_trades: true,
                    include_equity: true,
                }),
            });
            if (!response.ok) throw new Error("Backtest failed");
            const payload: BacktestResponse = await response.json();
            setBacktestResult(payload);
        } catch (err) {
            console.error(err);
            setError("Unable to run backtest. Check inputs and data availability.");
        } finally {
            setLoading(false);
        }
    };

    const runWalkForward = async () => {
        setLoading(true);
        setError(null);
        try {
            const baseUrl = getApiBaseUrl();
            const params = strategyParams ? JSON.parse(strategyParams) : {};
            const response = await fetch(`${baseUrl}/backtests/walk-forward`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    symbol,
                    exchange,
                    start: new Date(start).toISOString(),
                    end: new Date(end).toISOString(),
                    timeframe,
                    source: "auto",
                    strategy,
                    strategy_params: params,
                    train_window: trainWindow,
                    test_window: testWindow,
                    step_window: stepWindow,
                    initial_cash: initialCash,
                    fee_rate: feeRate,
                    slippage_bps: slippageBps,
                    max_position_pct: maxPositionPct,
                    store_report: true,
                }),
            });
            if (!response.ok) throw new Error("Walk-forward failed");
            const payload: WalkForwardResponse = await response.json();
            setWalkForwardResult(payload);
        } catch (err) {
            console.error(err);
            setError("Unable to run walk-forward. Check inputs and data availability.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="p-8 max-w-7xl mx-auto space-y-10">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-white">Backtesting Lab</h1>
                    <p className="text-sm text-gray-400 mt-2">
                        Run strategy experiments, inspect trades, and validate performance with walk-forward analysis.
                    </p>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-400">
                    <FlaskConical className="h-4 w-4 text-primary" />
                    Strategy research mode
                </div>
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
                    {error}
                </div>
            )}

            <section className="rounded-xl border border-white/10 bg-surface/60 p-6 space-y-6">
                <div className="flex items-center gap-3">
                    <TrendingUp className="h-5 w-5 text-primary" />
                    <h2 className="text-lg font-semibold text-white">Backtest Runner</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label className="text-xs text-gray-400">Symbol</label>
                        <input
                            value={symbol}
                            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Exchange</label>
                        <select
                            value={exchange}
                            onChange={(e) => setExchange(e.target.value)}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        >
                            <option value="coinbase">Coinbase</option>
                            <option value="kraken">Kraken</option>
                            <option value="binance">Binance US</option>
                        </select>
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Timeframe</label>
                        <select
                            value={timeframe}
                            onChange={(e) => setTimeframe(e.target.value)}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        >
                            <option value="1m">1m</option>
                            <option value="5m">5m</option>
                            <option value="15m">15m</option>
                            <option value="1h">1h</option>
                        </select>
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Start</label>
                        <input
                            type="datetime-local"
                            value={start}
                            onChange={(e) => setStart(e.target.value)}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">End</label>
                        <input
                            type="datetime-local"
                            value={end}
                            onChange={(e) => setEnd(e.target.value)}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Strategy</label>
                        <select
                            value={strategy}
                            onChange={(e) => setStrategy(e.target.value)}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        >
                            <option value="sma_cross">SMA Cross</option>
                            <option value="rsi">RSI</option>
                            <option value="buy_hold">Buy & Hold</option>
                            <option value="formula_long_momentum">Formula Long Momentum</option>
                            <option value="formula_quick_short">Formula Quick Short</option>
                            <option value="formula_dual_sleeve">Formula Dual Sleeve</option>
                        </select>
                    </div>
                    <div className="md:col-span-2">
                        <label className="text-xs text-gray-400">Strategy Params (JSON)</label>
                        <input
                            value={strategyParams}
                            onChange={(e) => setStrategyParams(e.target.value)}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Initial Cash</label>
                        <input
                            type="number"
                            value={initialCash}
                            onChange={(e) => setInitialCash(parseFloat(e.target.value))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Fee Rate</label>
                        <input
                            type="number"
                            step="0.0001"
                            value={feeRate}
                            onChange={(e) => setFeeRate(parseFloat(e.target.value))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Slippage (bps)</label>
                        <input
                            type="number"
                            value={slippageBps}
                            onChange={(e) => setSlippageBps(parseFloat(e.target.value))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Max Position %</label>
                        <input
                            type="number"
                            step="0.1"
                            value={maxPositionPct}
                            onChange={(e) => setMaxPositionPct(parseFloat(e.target.value))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                </div>
                <button
                    onClick={runBacktest}
                    className="rounded-lg bg-primary/20 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/30"
                >
                    {loading ? "Running..." : "Run Backtest"}
                </button>
            </section>

            {backtestResult && (
                <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 space-y-4">
                        <div className="rounded-xl border border-white/10 bg-surface/60 p-4">
                            <MarketChart data={equitySeries} />
                        </div>
                        <div className="rounded-xl border border-white/10 bg-surface/60 overflow-hidden">
                            <div className="p-4 border-b border-white/10 text-sm font-semibold text-gray-300">
                                Trade Ledger
                            </div>
                            <table className="w-full text-left text-xs">
                                <thead className="text-gray-500 border-b border-white/5">
                                    <tr>
                                        <th className="px-4 py-2">Time</th>
                                        <th className="px-4 py-2">Side</th>
                                        <th className="px-4 py-2">Price</th>
                                        <th className="px-4 py-2">Qty</th>
                                        <th className="px-4 py-2">PnL</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(backtestResult.trades || []).slice(0, 15).map((trade, idx) => (
                                        <tr key={`${trade.timestamp}-${idx}`} className="border-b border-white/5">
                                            <td className="px-4 py-2 text-gray-400">{trade.timestamp}</td>
                                            <td className="px-4 py-2 text-gray-200 uppercase">{trade.side}</td>
                                            <td className="px-4 py-2 text-gray-200">{trade.price?.toFixed?.(2) || trade.price}</td>
                                            <td className="px-4 py-2 text-gray-400">{trade.quantity?.toFixed?.(4) || trade.quantity}</td>
                                            <td className="px-4 py-2 text-gray-200">{trade.pnl?.toFixed?.(2) ?? "n/a"}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div className="space-y-4">
                        <div className="rounded-xl border border-white/10 bg-surface/60 p-4 space-y-3">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-gray-400">Run Metrics</span>
                                <BarChart3 className="h-4 w-4 text-primary" />
                            </div>
                            <div className="grid grid-cols-2 gap-3 text-xs text-gray-400">
                                {Object.entries(backtestResult.metrics || {}).map(([key, value]) => (
                                    <div key={key} className="rounded border border-white/5 bg-black/20 p-3">
                                        <div className="uppercase text-[10px] tracking-wide">{key.replace(/_/g, " ")}</div>
                                        <div className="truncate text-sm font-semibold text-white">{formatMetricValue(value)}</div>
                                    </div>
                                ))}
                            </div>
                            <div className="text-xs text-gray-500">
                                Source: {backtestResult.source} | Bucket {backtestResult.bucket_seconds}s
                            </div>
                        </div>
                    </div>
                </section>
            )}

            <section className="rounded-xl border border-white/10 bg-surface/60 p-6 space-y-6">
                <div className="flex items-center gap-3">
                    <BarChart3 className="h-5 w-5 text-primary" />
                    <h2 className="text-lg font-semibold text-white">Walk-Forward Evaluation</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label className="text-xs text-gray-400">Train Window (candles)</label>
                        <input
                            type="number"
                            value={trainWindow}
                            onChange={(e) => setTrainWindow(parseInt(e.target.value, 10))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Test Window (candles)</label>
                        <input
                            type="number"
                            value={testWindow}
                            onChange={(e) => setTestWindow(parseInt(e.target.value, 10))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                    <div>
                        <label className="text-xs text-gray-400">Step Window (candles)</label>
                        <input
                            type="number"
                            value={stepWindow}
                            onChange={(e) => setStepWindow(parseInt(e.target.value, 10))}
                            className="mt-2 w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                    </div>
                </div>
                <button
                    onClick={runWalkForward}
                    className="rounded-lg bg-primary/20 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/30"
                >
                    {loading ? "Running..." : "Run Walk-Forward"}
                </button>

                {walkForwardResult && (
                    <div className="space-y-4">
                        <div className="rounded-xl border border-white/10 bg-black/30 p-4 text-sm text-gray-300">
                            <div className="font-semibold text-white mb-2">Summary</div>
                            <pre className="text-xs whitespace-pre-wrap text-gray-400">
                                {JSON.stringify(walkForwardResult.summary, null, 2)}
                            </pre>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-surface/60 overflow-hidden">
                            <div className="p-4 border-b border-white/10 text-sm font-semibold text-gray-300">
                                Window Results
                            </div>
                            <table className="w-full text-left text-xs">
                                <thead className="text-gray-500 border-b border-white/5">
                                    <tr>
                                        <th className="px-4 py-2">Window</th>
                                        <th className="px-4 py-2">Test Start</th>
                                        <th className="px-4 py-2">Test End</th>
                                        <th className="px-4 py-2">Return %</th>
                                        <th className="px-4 py-2">Sharpe</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {walkForwardResult.windows.map((window) => (
                                        <tr key={`wf-${window.index}`} className="border-b border-white/5">
                                            <td className="px-4 py-2 text-gray-400">{window.index}</td>
                                            <td className="px-4 py-2 text-gray-400">{window.test_start}</td>
                                            <td className="px-4 py-2 text-gray-400">{window.test_end}</td>
                                            <td className="px-4 py-2 text-gray-200">
                                                {window.metrics?.total_return_pct?.toFixed?.(2) ?? "n/a"}
                                            </td>
                                            <td className="px-4 py-2 text-gray-200">
                                                {window.metrics?.sharpe_ratio?.toFixed?.(2) ?? "n/a"}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </section>
        </main>
    );
}

function formatMetricValue(value: unknown) {
    if (typeof value === "number") return value.toFixed(3);
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "n/a";
    return JSON.stringify(value);
}
