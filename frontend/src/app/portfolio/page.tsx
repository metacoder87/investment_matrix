"use client";

import { useEffect, useState } from "react";
import { Wallet, TrendingUp, TrendingDown, Plus, PieChart, ArrowUpRight, ArrowDownRight } from "lucide-react";

interface Holding {
    symbol: string;
    quantity: number;
    avg_entry_price: number;
    current_price: number;
    value: number;
    unrealized_pnl: number;
    pnl_percent: number;
}

interface PortfolioSummary {
    id: number;
    name: string;
    total_value: number;
    total_cost: number;
    unrealized_pnl: number;
    holdings: Holding[];
}

export default function PortfolioPage() {
    const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [isTradeModalOpen, setIsTradeModalOpen] = useState(false);

    // Forms
    const [newPortfolioName, setNewPortfolioName] = useState("");
    const [tradeForm, setTradeForm] = useState({
        symbol: "BTC-USD",
        exchange: "COINBASE",
        side: "buy",
        price: 0,
        amount: 0
    });

    // 1. Fetch Portfolio (Default ID 1 for MVP)
    const fetchPortfolio = async () => {
        try {
            const res = await fetch("http://localhost:8000/api/portfolio/1");
            if (res.ok) {
                const data = await res.json();
                setPortfolio(data);
            } else {
                setPortfolio(null);
            }
        } catch (error) {
            console.error(error);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchPortfolio();
        // Poll for updates (live PnL)
        const interval = setInterval(fetchPortfolio, 5000);
        return () => clearInterval(interval);
    }, []);

    const handleCreatePortfolio = async () => {
        const res = await fetch("http://localhost:8000/api/portfolio/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newPortfolioName })
        });
        if (res.ok) {
            setIsCreateModalOpen(false);
            fetchPortfolio(); // Refresh (will try to fetch ID 1)
        }
    };

    const handleSubmitTrade = async () => {
        if (!portfolio) return;

        const res = await fetch(`http://localhost:8000/api/portfolio/${portfolio.id}/orders`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(tradeForm)
        });

        if (res.ok) {
            setIsTradeModalOpen(false);
            fetchPortfolio();
        } else {
            alert("Failed to place order");
        }
    };

    if (isLoading) return <div className="p-8 text-gray-500">Loading portfolio...</div>;

    if (!portfolio) {
        return (
            <main className="p-8 max-w-7xl mx-auto flex flex-col items-center justify-center min-h-[50vh]">
                <Wallet className="h-16 w-16 text-gray-600 mb-4" />
                <h1 className="text-2xl font-bold text-white mb-2">No Portfolio Found</h1>
                <p className="text-gray-400 mb-6">Create your first portfolio to start tracking assets.</p>
                <button
                    onClick={() => setIsCreateModalOpen(true)}
                    className="px-6 py-3 bg-primary text-black font-bold rounded-lg hover:bg-cyan-400 transition-colors"
                >
                    Create Portfolio
                </button>

                {isCreateModalOpen && (
                    <div className="fixed inset-0 bg-black/80 flex items-center justify-center backdrop-blur-sm">
                        <div className="bg-surface border border-white/10 p-6 rounded-xl w-96">
                            <h3 className="text-xl font-bold text-white mb-4">Name your Portfolio</h3>
                            <input
                                type="text"
                                className="w-full bg-black/50 border border-white/20 rounded p-2 text-white mb-4"
                                placeholder="e.g. Main Fund"
                                value={newPortfolioName}
                                onChange={e => setNewPortfolioName(e.target.value)}
                            />
                            <div className="flex justify-end gap-2">
                                <button onClick={() => setIsCreateModalOpen(false)} className="px-4 py-2 text-gray-400">Cancel</button>
                                <button onClick={handleCreatePortfolio} className="px-4 py-2 bg-primary text-black rounded font-bold">Create</button>
                            </div>
                        </div>
                    </div>
                )}
            </main>
        );
    }

    return (
        <main className="p-8 max-w-7xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-3xl font-bold text-white mb-1">{portfolio.name}</h1>
                    <span className="text-sm text-gray-500 flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                        Live Optimization Active
                    </span>
                </div>
                <button
                    onClick={() => setIsTradeModalOpen(true)}
                    className="flex items-center gap-2 px-4 py-2 bg-primary/20 text-primary border border-primary/30 rounded-lg hover:bg-primary/30 transition-colors"
                >
                    <Plus className="h-4 w-4" />
                    New Trade
                </button>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <div className="text-sm text-gray-400 mb-2">Total Balance</div>
                    <div className="text-3xl font-bold font-mono text-white">
                        ${portfolio.total_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <div className="text-sm text-gray-400 mb-2">Unrealized PnL</div>
                    <div className={`text-3xl font-bold font-mono flex items-center gap-2 ${portfolio.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {portfolio.unrealized_pnl >= 0 ? '+' : ''}
                        ${portfolio.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        <span className={`text-sm px-2 py-1 rounded-full ${portfolio.unrealized_pnl >= 0 ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
                            {((portfolio.unrealized_pnl / (portfolio.total_cost || 1)) * 100).toFixed(2)}%
                        </span>
                    </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <div className="text-sm text-gray-400 mb-2">Total Cost Basis</div>
                    <div className="text-3xl font-bold font-mono text-gray-300">
                        ${portfolio.total_cost.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </div>
                </div>
            </div>

            {/* Holdings Table */}
            <div className="rounded-xl border border-white/10 bg-surface/50 overflow-hidden">
                <div className="p-4 border-b border-white/10 bg-white/5 flex items-center justify-between">
                    <h2 className="font-semibold text-gray-200">Current Holdings</h2>
                    <PieChart className="h-5 w-5 text-gray-500" />
                </div>

                {portfolio.holdings.length === 0 ? (
                    <div className="p-8 text-center text-gray-500">
                        No assets in this portfolio. Add a trade to get started.
                    </div>
                ) : (
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="text-xs text-gray-500 border-b border-white/5">
                                <th className="p-4 font-medium">Asset</th>
                                <th className="p-4 font-medium text-right">Qty</th>
                                <th className="p-4 font-medium text-right">Avg Entry</th>
                                <th className="p-4 font-medium text-right">Current Price</th>
                                <th className="p-4 font-medium text-right">Value</th>
                                <th className="p-4 font-medium text-right">PnL</th>
                            </tr>
                        </thead>
                        <tbody>
                            {portfolio.holdings.map((h) => (
                                <tr key={h.symbol} className="border-b border-white/5 hover:bg-white/[0.02]">
                                    <td className="p-4 font-bold text-white">{h.symbol}</td>
                                    <td className="p-4 text-right font-mono text-gray-300">{h.quantity}</td>
                                    <td className="p-4 text-right font-mono text-gray-400">${h.avg_entry_price.toFixed(2)}</td>
                                    <td className="p-4 text-right font-mono text-white">${h.current_price?.toFixed(2) || "---"}</td>
                                    <td className="p-4 text-right font-mono text-white font-medium">${h.value?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || "---"}</td>
                                    <td className={`p-4 text-right font-mono font-bold ${h.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        <div className="flex items-center justify-end gap-1">
                                            {h.unrealized_pnl >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                                            ${Math.abs(h.unrealized_pnl).toFixed(2)}
                                            <span className="opacity-50 text-xs">({h.pnl_percent.toFixed(2)}%)</span>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* Trade Modal */}
            {isTradeModalOpen && (
                <div className="fixed inset-0 bg-black/80 flex items-center justify-center backdrop-blur-sm z-50">
                    <div className="bg-[#121212] border border-white/10 p-6 rounded-xl w-[400px] shadow-2xl">
                        <h3 className="text-xl font-bold text-white mb-6">Add Transaction</h3>

                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs text-gray-500 mb-1">Pair</label>
                                <input
                                    className="w-full bg-white/5 border border-white/10 rounded p-2 text-white"
                                    value={tradeForm.symbol}
                                    onChange={e => setTradeForm({ ...tradeForm, symbol: e.target.value.toUpperCase() })}
                                />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs text-gray-500 mb-1">Side</label>
                                    <select
                                        className="w-full bg-white/5 border border-white/10 rounded p-2 text-white"
                                        value={tradeForm.side}
                                        onChange={e => setTradeForm({ ...tradeForm, side: e.target.value })}
                                    >
                                        <option value="buy">Buy</option>
                                        <option value="sell">Sell</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs text-gray-500 mb-1">Exchange</label>
                                    <select
                                        className="w-full bg-white/5 border border-white/10 rounded p-2 text-white"
                                        value={tradeForm.exchange}
                                        onChange={e => setTradeForm({ ...tradeForm, exchange: e.target.value })}
                                    >
                                        <option value="COINBASE">Coinbase</option>
                                        <option value="BINANCE">Binance</option>
                                        <option value="KRAKEN">Kraken</option>
                                    </select>
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs text-gray-500 mb-1">Price</label>
                                    <input
                                        type="number"
                                        className="w-full bg-white/5 border border-white/10 rounded p-2 text-white"
                                        value={tradeForm.price || ""}
                                        onChange={e => setTradeForm({ ...tradeForm, price: parseFloat(e.target.value) })}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs text-gray-500 mb-1">Amount</label>
                                    <input
                                        type="number"
                                        className="w-full bg-white/5 border border-white/10 rounded p-2 text-white"
                                        value={tradeForm.amount || ""}
                                        onChange={e => setTradeForm({ ...tradeForm, amount: parseFloat(e.target.value) })}
                                    />
                                </div>
                            </div>

                            <div className="pt-4 flex gap-3">
                                <button
                                    onClick={() => setIsTradeModalOpen(false)}
                                    className="flex-1 py-3 rounded-lg border border-white/10 text-gray-400 hover:bg-white/5 transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleSubmitTrade}
                                    className="flex-1 py-3 rounded-lg bg-primary text-black font-bold hover:bg-cyan-400 transition-colors"
                                >
                                    Submit
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </main>
    );
}

