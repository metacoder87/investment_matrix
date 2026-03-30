"use client";

import { useEffect, useState } from "react";
import { Search, Plus, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { getApiBaseUrl } from "@/utils/api";

interface SearchCoinModalProps {
    isOpen: boolean;
    onClose: () => void;
    onCoinAdded: () => void;
}

interface CoinSearchResult {
    id: string;
    symbol: string;
    name: string;
    thumb?: string;
    market_cap_rank?: number;
}

export default function SearchCoinModal({ isOpen, onClose, onCoinAdded }: SearchCoinModalProps) {
    const [query, setQuery] = useState("");
    const [results, setResults] = useState<CoinSearchResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [adding, setAdding] = useState<string | null>(null);
    const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

    useEffect(() => {
        if (!isOpen) {
            return;
        }

        const timeoutId = setTimeout(() => {
            void handleSearch(query);
        }, 500);

        return () => clearTimeout(timeoutId);
    }, [isOpen, query]);

    const handleSearch = async (searchQuery: string) => {
        if (!searchQuery || searchQuery.length < 2) {
            setResults([]);
            return;
        }

        setLoading(true);
        setMessage(null);

        try {
            const apiUrl = getApiBaseUrl();
            const response = await fetch(`${apiUrl}/coins/search?q=${encodeURIComponent(searchQuery)}&limit=15`);

            if (!response.ok) {
                throw new Error(`Search failed: ${response.status}`);
            }

            const data = await response.json();
            setResults(data || []);
        } catch (err) {
            console.error("Search error:", err);
            setMessage({ type: "error", text: "Search failed. Please try again." });
            setResults([]);
        } finally {
            setLoading(false);
        }
    };

    const handleAddCoin = async (coin: CoinSearchResult) => {
        setAdding(coin.id);
        setMessage(null);

        try {
            const apiUrl = getApiBaseUrl();
            const response = await fetch(`${apiUrl}/coins/add`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: coin.id,
                    coingecko_id: coin.id,
                    symbol: coin.symbol,
                    name: coin.name
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to add coin: ${response.status}`);
            }

            const data = await response.json();

            if (data.existed) {
                setMessage({ type: "success", text: `${coin.symbol.toUpperCase()} already in database` });
            } else {
                setMessage({ type: "success", text: `${coin.symbol.toUpperCase()} added! Backfill queued.` });

                // Notify parent component to refresh
                setTimeout(() => {
                    onCoinAdded();
                    onClose();
                }, 1500);
            }
        } catch (err) {
            console.error("Add coin error:", err);
            setMessage({ type: "error", text: `Failed to add ${coin.symbol}. Please try again.` });
        } finally {
            setAdding(null);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="relative w-full max-w-2xl rounded-2xl border border-white/10 bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-6 shadow-2xl">
                {/* Header */}
                <div className="mb-4 flex items-center justify-between">
                    <h2 className="text-2xl font-bold text-white">Search &amp; Add Coins</h2>
                    <button
                        onClick={onClose}
                        className="rounded-full p-2 text-gray-400 transition-colors hover:bg-white/10 hover:text-white"
                    >
                        <XCircle className="h-6 w-6" />
                    </button>
                </div>

                {/* Search Input */}
                <div className="relative mb-4">
                    <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search by name or symbol (e.g., Polygon, MATIC)..."
                        className="w-full rounded-lg border border-white/10 bg-black/40 py-3 pl-10 pr-4 text-white placeholder-gray-500 focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
                        autoFocus
                    />
                </div>

                {/* Message */}
                {message && (
                    <div className={`mb-4 rounded-lg border p-3 ${message.type === "success"
                            ? "border-green-500/30 bg-green-500/10 text-green-400"
                            : "border-red-500/30 bg-red-500/10 text-red-400"
                        }`}>
                        <div className="flex items-center gap-2">
                            {message.type === "success" ? (
                                <CheckCircle2 className="h-5 w-5" />
                            ) : (
                                <XCircle className="h-5 w-5" />
                            )}
                            <span>{message.text}</span>
                        </div>
                    </div>
                )}

                {/* Results */}
                <div className="max-h-96 overflow-y-auto rounded-lg border border-white/10 bg-black/20">
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <Loader2 className="h-8 w-8 animate-spin text-cyan-400" />
                            <span className="ml-2 text-gray-400">Searching...</span>
                        </div>
                    ) : results.length > 0 ? (
                        <div className="divide-y divide-white/5">
                            {results.map((coin) => (
                                <div
                                    key={coin.id}
                                    className="flex items-center justify-between p-4 transition-colors hover:bg-white/5"
                                >
                                    <div className="flex items-center gap-3">
                                        {coin.thumb && (
                                            <img
                                                src={coin.thumb}
                                                alt={coin.symbol}
                                                className="h-8 w-8 rounded-full"
                                            />
                                        )}
                                        <div>
                                            <div className="font-semibold text-white">
                                                {coin.name}
                                                {coin.market_cap_rank && (
                                                    <span className="ml-2 text-xs text-gray-500">
                                                        #{coin.market_cap_rank}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-sm text-gray-400">
                                                {coin.symbol.toUpperCase()}
                                            </div>
                                        </div>
                                    </div>

                                    <button
                                        onClick={() => handleAddCoin(coin)}
                                        disabled={adding === coin.id}
                                        className="flex items-center gap-2 rounded-lg bg-cyan-500/20 px-4 py-2 text-sm font-medium text-cyan-400 transition-colors hover:bg-cyan-500/30 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        {adding === coin.id ? (
                                            <>
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                Adding...
                                            </>
                                        ) : (
                                            <>
                                                <Plus className="h-4 w-4" />
                                                Add
                                            </>
                                        )}
                                    </button>
                                </div>
                            ))}
                        </div>
                    ) : query.length >= 2 && !loading ? (
                        <div className="py-12 text-center text-gray-500">
                            No coins found for "{query}"
                        </div>
                    ) : (
                        <div className="py-12 text-center text-gray-500">
                            Start typing to search for coins...
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="mt-4 text-center text-xs text-gray-500">
                    Search powered by CoinGecko API
                </div>
            </div>
        </div>
    );
}
