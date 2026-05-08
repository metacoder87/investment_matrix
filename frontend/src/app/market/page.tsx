"use client";

import { useState } from "react";
import { CoinsTable } from "@/components/CoinsTable";
import { MarketOperationsPanel } from "@/components/MarketOperationsPanel";
import SearchCoinModal from "@/components/SearchCoinModal";
import { LineChart, Plus } from "lucide-react";

export default function MarketPage() {
    const [isSearchModalOpen, setIsSearchModalOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);

    const handleCoinAdded = () => {
        setRefreshKey((prev) => prev + 1);
    };

    return (
        <main className="mx-auto max-w-[1600px] space-y-6 p-4 md:p-8">
            {/* Header */}
            <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                <div>
                    <h1 className="flex items-center gap-3 font-mono text-3xl font-bold uppercase tracking-wider text-primary neon-text">
                        <LineChart className="h-7 w-7" />
                        Market Grid
                    </h1>
                    <p className="mt-1 text-sm text-gray-400">
                        Dense coin lists, signals, and bot eligibility. Add new tickers from
                        across exchanges.
                    </p>
                </div>
                <button
                    onClick={() => setIsSearchModalOpen(true)}
                    className="inline-flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-4 py-2 font-mono text-sm font-semibold uppercase tracking-wider text-primary shadow-neon-cyan transition hover:bg-primary/20"
                >
                    <Plus className="h-5 w-5" />
                    Search & Add Coin
                </button>
            </div>

            {/* Operations panel */}
            <div className="neo-card">
                <MarketOperationsPanel />
            </div>

            {/* Coin list */}
            <div className="neo-card overflow-hidden">
                <CoinsTable key={refreshKey} />
            </div>

            <SearchCoinModal
                isOpen={isSearchModalOpen}
                onClose={() => setIsSearchModalOpen(false)}
                onCoinAdded={handleCoinAdded}
            />
        </main>
    );
}
