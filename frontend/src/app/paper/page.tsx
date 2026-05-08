"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, PlayCircle, ShieldCheck, Timer } from "lucide-react";
import { getApiBaseUrl } from "@/utils/api";

interface PaperAccount {
    id: number;
    name: string;
    base_currency: string;
    cash_balance: number;
    equity: number;
    last_signal?: string | null;
    last_step_at?: string | null;
    equity_peak?: number | null;
}

interface PaperPosition {
    symbol: string;
    exchange: string;
    side: string;
    quantity: number;
    avg_entry_price: number;
    last_price: number;
    reserved_collateral?: number;
    take_profit?: number | null;
    stop_loss?: number | null;
}

interface PaperOrder {
    id: number;
    symbol: string;
    exchange: string;
    side: string;
    status: string;
    price: number;
    quantity: number;
    timestamp?: string;
}

interface PaperSchedule {
    id: number;
    account_id: number;
    symbol: string;
    exchange: string;
    timeframe: string;
    lookback: number;
    strategy: string;
    interval_seconds: number;
    max_drawdown_pct?: number | null;
    is_active: boolean;
    disabled_reason?: string | null;
    last_run_at?: string | null;
}

const strategyDefaults: Record<string, string> = {
    sma_cross: '{"short_window": 20, "long_window": 50}',
    rsi: '{"length": 14, "buy_threshold": 30, "sell_threshold": 70}',
    buy_hold: "{}",
    formula_long_momentum: "{}",
    formula_quick_short: "{}",
    formula_dual_sleeve: "{}",
};

export default function PaperTradingPage() {
    const [accounts, setAccounts] = useState<PaperAccount[]>([]);
    const [selectedAccount, setSelectedAccount] = useState<number | null>(null);
    const [positions, setPositions] = useState<PaperPosition[]>([]);
    const [orders, setOrders] = useState<PaperOrder[]>([]);
    const [schedules, setSchedules] = useState<PaperSchedule[]>([]);

    const [accountName, setAccountName] = useState("");
    const [accountCash, setAccountCash] = useState(10000);

    const [symbol, setSymbol] = useState("BTC-USD");
    const [exchange, setExchange] = useState("coinbase");
    const [timeframe, setTimeframe] = useState("1m");
    const [lookback, setLookback] = useState(200);
    const [strategy, setStrategy] = useState("sma_cross");
    const [strategyParams, setStrategyParams] = useState(strategyDefaults.sma_cross);

    const [intervalSeconds, setIntervalSeconds] = useState(60);
    const [maxDrawdownPct, setMaxDrawdownPct] = useState<number | "">("");

    const [status, setStatus] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const activeAccount = useMemo(
        () => accounts.find((acct) => acct.id === selectedAccount) || null,
        [accounts, selectedAccount]
    );

    const loadAccounts = async () => {
        const baseUrl = getApiBaseUrl();
        const resp = await fetch(`${baseUrl}/paper/accounts`);
        if (!resp.ok) return;
        const payload = await resp.json();
        setAccounts(payload);
        if (payload.length && selectedAccount === null) {
            setSelectedAccount(payload[0].id);
        }
    };

    const loadPositions = async (accountId: number) => {
        const baseUrl = getApiBaseUrl();
        const resp = await fetch(`${baseUrl}/paper/accounts/${accountId}/positions`);
        if (!resp.ok) return;
        setPositions(await resp.json());
    };

    const loadOrders = async (accountId: number) => {
        const baseUrl = getApiBaseUrl();
        const resp = await fetch(`${baseUrl}/paper/accounts/${accountId}/orders?limit=10`);
        if (!resp.ok) return;
        setOrders(await resp.json());
    };

    const loadSchedules = async () => {
        const baseUrl = getApiBaseUrl();
        const resp = await fetch(`${baseUrl}/paper/schedules`);
        if (!resp.ok) return;
        setSchedules(await resp.json());
    };

    useEffect(() => {
        loadAccounts();
        loadSchedules();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const requestedSymbol = new URLSearchParams(window.location.search).get("symbol");
        if (requestedSymbol) {
            setSymbol(requestedSymbol.toUpperCase());
        }
    }, []);

    useEffect(() => {
        if (selectedAccount === null) return;
        loadPositions(selectedAccount);
        loadOrders(selectedAccount);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedAccount]);

    const handleCreateAccount = async () => {
        setLoading(true);
        setStatus(null);
        try {
            const baseUrl = getApiBaseUrl();
            const resp = await fetch(`${baseUrl}/paper/accounts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: accountName, cash_balance: accountCash }),
            });
            if (!resp.ok) throw new Error("Failed to create account");
            await loadAccounts();
            setAccountName("");
            setStatus("Paper account created.");
        } catch (err) {
            console.error(err);
            setStatus("Unable to create account.");
        } finally {
            setLoading(false);
        }
    };

    const handleStep = async () => {
        if (!selectedAccount) return;
        setLoading(true);
        setStatus(null);
        try {
            const baseUrl = getApiBaseUrl();
            const params = strategyParams ? JSON.parse(strategyParams) : {};
            const resp = await fetch(`${baseUrl}/paper/accounts/${selectedAccount}/step`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    symbol,
                    exchange,
                    timeframe,
                    lookback,
                    source: "auto",
                    strategy,
                    strategy_params: params,
                }),
            });
            if (!resp.ok) throw new Error("Step failed");
            await loadAccounts();
            await loadPositions(selectedAccount);
            await loadOrders(selectedAccount);
            setStatus("Paper step executed.");
        } catch (err) {
            console.error(err);
            setStatus("Unable to execute step.");
        } finally {
            setLoading(false);
        }
    };

    const handleCreateSchedule = async () => {
        if (!selectedAccount) return;
        setLoading(true);
        setStatus(null);
        try {
            const baseUrl = getApiBaseUrl();
            const params = strategyParams ? JSON.parse(strategyParams) : {};
            const resp = await fetch(`${baseUrl}/paper/schedules`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    account_id: selectedAccount,
                    symbol,
                    exchange,
                    timeframe,
                    lookback,
                    source: "auto",
                    strategy,
                    strategy_params: params,
                    interval_seconds: intervalSeconds,
                    max_drawdown_pct: maxDrawdownPct === "" ? null : Number(maxDrawdownPct),
                }),
            });
            if (!resp.ok) throw new Error("Schedule failed");
            await loadSchedules();
            setStatus("Schedule created.");
        } catch (err) {
            console.error(err);
            setStatus("Unable to create schedule.");
        } finally {
            setLoading(false);
        }
    };

    const toggleSchedule = async (schedule: PaperSchedule) => {
        setLoading(true);
        try {
            const baseUrl = getApiBaseUrl();
            await fetch(`${baseUrl}/paper/schedules/${schedule.id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ is_active: !schedule.is_active }),
            });
            await loadSchedules();
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="p-8 max-w-7xl mx-auto space-y-10">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-white">Paper Trading</h1>
                    <p className="text-sm text-gray-400 mt-2">
                        Simulated execution loop with real-time data, guardrails, and portfolio telemetry.
                    </p>
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    Safe execution mode
                </div>
            </div>

            {status && (
                <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs text-gray-300">
                    {status}
                </div>
            )}

            <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="rounded-xl border border-white/10 bg-surface/60 p-6 space-y-4">
                    <div className="flex items-center gap-3">
                        <Bot className="h-5 w-5 text-primary" />
                        <h2 className="text-lg font-semibold">Accounts</h2>
                    </div>
                    <div className="space-y-2">
                        <input
                            placeholder="Account name"
                            value={accountName}
                            onChange={(e) => setAccountName(e.target.value)}
                            className="w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                        <input
                            type="number"
                            value={accountCash}
                            onChange={(e) => setAccountCash(parseFloat(e.target.value))}
                            className="w-full rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        />
                        <button
                            onClick={handleCreateAccount}
                            className="w-full rounded-lg bg-primary/20 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/30"
                        >
                            {loading ? "Working..." : "Create Account"}
                        </button>
                    </div>
                    <div className="space-y-2">
                        {accounts.map((acct) => (
                            <button
                                key={acct.id}
                                onClick={() => setSelectedAccount(acct.id)}
                                className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                                    selectedAccount === acct.id
                                        ? "border-primary/40 bg-primary/10 text-primary"
                                        : "border-white/10 bg-black/30 text-gray-300"
                                }`}
                            >
                                <div className="font-semibold">{acct.name}</div>
                                <div className="text-xs text-gray-400">
                                    Equity {acct.equity?.toFixed?.(2)} | Cash {acct.cash_balance?.toFixed?.(2)}
                                </div>
                            </button>
                        ))}
                    </div>
                </div>

                <div className="lg:col-span-2 space-y-6">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="rounded-xl border border-white/10 bg-surface/60 p-4">
                            <div className="text-xs text-gray-400">Equity</div>
                            <div className="text-2xl font-bold text-white">{activeAccount?.equity?.toFixed?.(2) || "--"}</div>
                            <div className="text-xs text-gray-500">Peak {activeAccount?.equity_peak?.toFixed?.(2) || "--"}</div>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-surface/60 p-4">
                            <div className="text-xs text-gray-400">Last Signal</div>
                            <div className="text-2xl font-bold text-white">{activeAccount?.last_signal || "--"}</div>
                            <div className="text-xs text-gray-500">Last step {activeAccount?.last_step_at || "--"}</div>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-surface/60 p-4">
                            <div className="text-xs text-gray-400">Open Positions</div>
                            <div className="text-2xl font-bold text-white">{positions.length}</div>
                            <div className="text-xs text-gray-500">Tracked orders {orders.length}</div>
                        </div>
                    </div>

                    <div className="rounded-xl border border-white/10 bg-surface/60 p-6 space-y-4">
                        <div className="flex items-center gap-3">
                            <PlayCircle className="h-5 w-5 text-primary" />
                            <h2 className="text-lg font-semibold">Run Step</h2>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <input
                                value={symbol}
                                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                                className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            />
                            <select
                                value={exchange}
                                onChange={(e) => setExchange(e.target.value)}
                                className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            >
                                <option value="coinbase">Coinbase</option>
                                <option value="kraken">Kraken</option>
                                <option value="binance">Binance US</option>
                            </select>
                            <select
                                value={timeframe}
                                onChange={(e) => setTimeframe(e.target.value)}
                                className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            >
                                <option value="1m">1m</option>
                                <option value="5m">5m</option>
                                <option value="15m">15m</option>
                                <option value="1h">1h</option>
                            </select>
                            <input
                                type="number"
                                value={lookback}
                                onChange={(e) => setLookback(parseInt(e.target.value, 10))}
                                className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            />
                            <select
                                value={strategy}
                                onChange={(e) => {
                                    setStrategy(e.target.value);
                                    setStrategyParams(strategyDefaults[e.target.value] || "{}");
                                }}
                                className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            >
                                <option value="sma_cross">SMA Cross</option>
                                <option value="rsi">RSI</option>
                                <option value="buy_hold">Buy & Hold</option>
                                <option value="formula_long_momentum">Formula Long Momentum</option>
                                <option value="formula_quick_short">Formula Quick Short</option>
                                <option value="formula_dual_sleeve">Formula Dual Sleeve</option>
                            </select>
                            <input
                                value={strategyParams}
                                onChange={(e) => setStrategyParams(e.target.value)}
                                className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            />
                        </div>
                        <button
                            onClick={handleStep}
                            className="rounded-lg bg-primary/20 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/30"
                        >
                            {loading ? "Working..." : "Execute Step"}
                        </button>
                    </div>
                </div>
            </section>

            <section className="rounded-xl border border-white/10 bg-surface/60 p-6 space-y-4">
                <div className="flex items-center gap-3">
                    <Timer className="h-5 w-5 text-primary" />
                    <h2 className="text-lg font-semibold">Scheduler</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <input
                        type="number"
                        value={intervalSeconds}
                        onChange={(e) => setIntervalSeconds(parseInt(e.target.value, 10))}
                        className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        placeholder="Interval seconds"
                    />
                    <input
                        type="number"
                        value={maxDrawdownPct}
                        onChange={(e) => setMaxDrawdownPct(e.target.value === "" ? "" : Number(e.target.value))}
                        className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                        placeholder="Max drawdown %"
                    />
                    <button
                        onClick={handleCreateSchedule}
                        className="rounded-lg bg-primary/20 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/30"
                    >
                        {loading ? "Working..." : "Create Schedule"}
                    </button>
                </div>

                <div className="rounded-xl border border-white/10 bg-black/30 overflow-hidden">
                    <table className="w-full text-left text-xs">
                        <thead className="text-gray-500 border-b border-white/10">
                            <tr>
                                <th className="px-4 py-2">Symbol</th>
                                <th className="px-4 py-2">Interval</th>
                                <th className="px-4 py-2">Strategy</th>
                                <th className="px-4 py-2">Status</th>
                                <th className="px-4 py-2">Last Run</th>
                                <th className="px-4 py-2"></th>
                            </tr>
                        </thead>
                        <tbody>
                            {schedules.map((schedule) => (
                                <tr key={schedule.id} className="border-b border-white/5">
                                    <td className="px-4 py-2 text-gray-200">{schedule.symbol}</td>
                                    <td className="px-4 py-2 text-gray-400">{schedule.interval_seconds}s</td>
                                    <td className="px-4 py-2 text-gray-400">{schedule.strategy}</td>
                                    <td className="px-4 py-2 text-gray-200">
                                        {schedule.is_active ? "Active" : schedule.disabled_reason || "Paused"}
                                    </td>
                                    <td className="px-4 py-2 text-gray-400">{schedule.last_run_at || "--"}</td>
                                    <td className="px-4 py-2">
                                        <button
                                            onClick={() => toggleSchedule(schedule)}
                                            className="rounded border border-white/10 px-2 py-1 text-xs text-gray-300 hover:text-white"
                                        >
                                            {schedule.is_active ? "Pause" : "Resume"}
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </section>
        </main>
    );
}
