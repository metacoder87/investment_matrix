"use client";

import { useEffect, useState } from "react";
import { ArrowUp, ArrowDown } from "lucide-react";
import Link from "next/link";
import { cn } from "@/utils/cn";

interface Coin {
    id: string;
    symbol: string;
    name: string;
    image: string;
    current_price: number;
    market_cap: number;
    price_change_percentage_24h: number;
}

export function CoinsTable() {
    const [coins, setCoins] = useState<Coin[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // In dev, we might hit localhost:8000 directly if CORS allows,
        // or use the proxy if we set one up in next.config.mjs (I didn't yet).
        // I put NEXT_PUBLIC_API_URL in docker-compose.
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

        fetch(`${apiUrl}/coins`)
            .then((res) => {
                if (!res.ok) throw new Error("Failed to fetch");
                return res.json();
            })
            .then((data) => {
                setCoins(data);
                setLoading(false);
            })
            .catch((err) => {
                console.error("Failed to fetch coins", err);
                setLoading(false);
            });
    }, []);

    if (loading) return <div className="text-center p-10 text-muted animate-pulse">Loading market data...</div>;

    return (
        <div className="rounded-xl border border-white/10 bg-surface/50 backdrop-blur-sm overflow-hidden">
            <table className="w-full text-left text-sm">
                <thead className="bg-white/5 text-gray-400">
                    <tr>
                        <th className="px-6 py-4 font-medium">Asset</th>
                        <th className="px-6 py-4 font-medium text-right">Price</th>
                        <th className="px-6 py-4 font-medium text-right">24h Change</th>
                        <th className="px-6 py-4 font-medium text-right">Market Cap</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                    {coins.map((coin) => (
                        <tr key={coin.id} className="hover:bg-white/5 transition-colors group">
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
                                ${coin.current_price?.toLocaleString()}
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
    );
}
