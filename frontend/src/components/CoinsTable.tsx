"use client";

import { useEffect, useState } from "react";
import { ArrowUp, ArrowDown } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/utils/cn";
import { formatPrice } from "@/utils/format";
import { getApiBaseUrl } from "@/utils/api";

interface Coin {
    id: string;
    symbol: string;
    name: string;
    image: string;
    current_price: number;
    market_cap: number;
    price_change_percentage_24h: number;
    analysis?: {
        signal: string | null;
        rsi: number | null;
        confidence: number | null;
    };
}

export function CoinsTable() {
    const router = useRouter();
    const [coins, setCoins] = useState<Coin[]>([]);
    const [loading, setLoading] = useState(true);
    const [sortConfig, setSortConfig] = useState<{ key: keyof Coin | "analysis.rsi" | "analysis.signal"; direction: "asc" | "desc" } | null>(null);

    const handleSort = (key: keyof Coin | "analysis.rsi" | "analysis.signal") => {
        let direction: "asc" | "desc" = "desc";
        if (sortConfig && sortConfig.key === key && sortConfig.direction === "desc") {
            direction = "asc";
        }
        setSortConfig({ key, direction });
    };

    const sortedCoins = [...coins].sort((a, b) => {
        if (!sortConfig) return 0;
        const { key, direction } = sortConfig;

        let aVal: any;
        let bVal: any;

        if (key === "analysis.signal") {
            const getScore = (sig: string | null | undefined) => {
                if (!sig) return 0;
                const s = sig.toUpperCase();
                if (s.includes("STRONG BUY")) return 5;
                if (s.includes("BUY")) return 4;
                if (s.includes("HOLD")) return 3;
                if (s.includes("NEUTRAL")) return 2.5;
                if (s.includes("SELL")) return 2;
                if (s.includes("STRONG SELL")) return 1;
                return 0;
            };
            aVal = getScore(a.analysis?.signal);
            bVal = getScore(b.analysis?.signal);
        } else if (key === "analysis.rsi") {
            aVal = a.analysis?.rsi ?? -1;
            bVal = b.analysis?.rsi ?? -1;
        } else {
            // @ts-ignore
            aVal = a[key] ?? (typeof a[key] === "string" ? "" : 0);
            // @ts-ignore
            bVal = b[key] ?? (typeof b[key] === "string" ? "" : 0);
        }

        if (aVal < bVal) return direction === "asc" ? -1 : 1;
        if (aVal > bVal) return direction === "asc" ? 1 : -1;
        return 0;
    });

    const SortIcon = ({ column }: { column: keyof Coin | "analysis.rsi" | "analysis.signal" }) => {
        if (sortConfig?.key !== column) return <span className="ml-1 opacity-20">--</span>;
        return sortConfig.direction === "asc" ? <ArrowUp size={14} className="ml-1 inline" /> : <ArrowDown size={14} className="ml-1 inline" />;
    };

    const getSignalBadge = (signal: string | null | undefined) => {
        if (!signal) return <span className="text-gray-600 text-xs">N/A</span>;
        const s = signal.toUpperCase();
        if (s.includes("STRONG BUY")) return <span className="bg-green-500/20 text-green-400 px-2 py-1 rounded text-xs font-bold border border-green-500/50">STRONG BUY</span>;
        if (s.includes("BUY")) return <span className="text-green-400 text-xs font-medium">BUY</span>;
        if (s.includes("STRONG SELL")) return <span className="bg-red-500/20 text-red-400 px-2 py-1 rounded text-xs font-bold border border-red-500/50">STRONG SELL</span>;
        if (s.includes("SELL")) return <span className="text-red-400 text-xs font-medium">SELL</span>;
        return <span className="text-gray-400 text-xs">NEUTRAL</span>;
    };

    const [searchQuery, setSearchQuery] = useState("");
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const apiUrl = getApiBaseUrl();

        fetch(`${apiUrl}/coins`)
            .then((res) => {
                if (!res.ok) throw new Error("Failed to fetch market data");
                return res.json();
            })
            .then((data) => {
                setCoins(data);
                setLoading(false);
            })
            .catch((err) => {
                console.error("Failed to fetch coins", err);
                setError("Unable to connect to Market API. Please check your connection.");
                setLoading(false);
            });
    }, []);

    if (loading) return <div className="text-center p-10 text-muted animate-pulse">Loading market data...</div>;

    if (error) return (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-8 text-center">
            <div className="mx-auto w-12 h-12 bg-red-500/10 rounded-full flex items-center justify-center mb-4">
                <ArrowDown className="text-red-500 w-6 h-6 rotate-45" /> {/* Use X icon if available, or just reuse arrow */}
            </div>
            <h3 className="text-white font-medium mb-1">Connection Failed</h3>
            <p className="text-gray-400 text-sm">{error}</p>
            <button
                onClick={() => window.location.reload()}
                className="mt-4 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm text-white transition-colors"
            >
                Retry Connection
            </button>
        </div>
    );

    const filteredCoins = sortedCoins.filter(c =>
        c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.symbol.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center bg-surface/50 p-4 rounded-xl border border-white/10 backdrop-blur-sm">
                <div className="w-full max-w-md">
                    <input
                        type="text"
                        placeholder="Filter coins (e.g. BTC, Solana, PEPE)..."
                        className="flex-1 bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-sm focus:ring-1 focus:ring-primary outline-none"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>
                <div className="text-xs text-gray-500">
                    Showing {filteredCoins.length} assets
                </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-surface/50 backdrop-blur-sm overflow-hidden">
                <table className="w-full text-left text-sm">
                    <thead className="bg-white/5 text-gray-400">
                        <tr>
                            <th className="px-6 py-4 font-medium uppercase tracking-wider">Asset</th>
                            <th
                                className="px-6 py-4 font-medium text-right cursor-pointer hover:text-white transition-colors select-none"
                                onClick={() => handleSort("current_price")}
                            >
                                Price <SortIcon column="current_price" />
                            </th>
                            <th
                                className="px-6 py-4 font-medium text-center cursor-pointer hover:text-white transition-colors select-none"
                                onClick={() => handleSort("analysis.rsi")}
                            >
                                RSI <SortIcon column="analysis.rsi" />
                            </th>
                            <th
                                className="px-6 py-4 font-medium text-center cursor-pointer hover:text-white transition-colors select-none"
                                onClick={() => handleSort("analysis.signal")}
                            >
                                Signal <SortIcon column="analysis.signal" />
                            </th>
                            <th
                                className="px-6 py-4 font-medium text-right cursor-pointer hover:text-white transition-colors select-none"
                                onClick={() => handleSort("price_change_percentage_24h")}
                            >
                                24h Change <SortIcon column="price_change_percentage_24h" />
                            </th>
                            <th
                                className="px-6 py-4 font-medium text-right cursor-pointer hover:text-white transition-colors select-none"
                                onClick={() => handleSort("market_cap")}
                            >
                                Market Cap <SortIcon column="market_cap" />
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {filteredCoins.map((coin) => (
                            <tr key={coin.id} className="hover:bg-white/5 transition-colors group cursor-pointer" onClick={() => router.push(`/market/${coin.symbol.toLowerCase()}`)}>
                                <td className="px-6 py-4">
                                    <Link href={`/market/${coin.symbol.toLowerCase()}`} className="flex items-center gap-3 hover:opacity-80 transition-opacity">
                                        <img src={coin.image} alt={coin.name} className="h-8 w-8 rounded-full" />
                                        <div>
                                            <div className="font-bold text-white group-hover:text-primary transition-colors">{coin.symbol.toUpperCase()}</div>
                                            <div className="text-xs text-gray-500">{coin.name}</div>
                                        </div>
                                    </Link>
                                </td>
                                <td className="px-6 py-4 text-right font-mono text-white">
                                    {formatPrice(coin.current_price)}
                                </td>
                                <td className="px-6 py-4 text-center font-mono text-gray-300">
                                    {coin.analysis?.rsi != null ? coin.analysis.rsi.toFixed(1) : "-"}
                                </td>
                                <td className="px-6 py-4 text-center">
                                    {getSignalBadge(coin.analysis?.signal)}
                                </td>
                                <td className="px-6 py-4 text-right font-mono">
                                    <div className={cn("inline-flex items-center gap-1", (coin.price_change_percentage_24h || 0) >= 0 ? "text-accent" : "text-red-500")}>
                                        {(coin.price_change_percentage_24h || 0) >= 0 ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
                                        {Math.abs(coin.price_change_percentage_24h || 0).toFixed(2)}%
                                    </div>
                                </td>
                                <td className="px-6 py-4 text-right text-gray-400">
                                    ${coin.market_cap?.toLocaleString()}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
