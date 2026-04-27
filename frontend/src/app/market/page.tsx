"use client";

import { useState } from "react";
import { CoinsTable } from "@/components/CoinsTable";
import { MarketOperationsPanel } from "@/components/MarketOperationsPanel";
import SearchCoinModal from "@/components/SearchCoinModal";
import { Plus } from "lucide-react";

export default function MarketPage() {
    const [isSearchModalOpen, setIsSearchModalOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);

    const handleCoinAdded = () => {
        // Increment key to force CoinsTable refresh
        setRefreshKey(prev => prev + 1);
    };

    return (
        <main className="mx-auto max-w-[1600px] p-4 md:p-8">
            {/* Header with Add Button */}
            <div className="flex items-center justify-between mb-6">
                <h1 className="text-3xl font-bold text-primary">Market Overview</h1>
                <button
                    onClick={() => setIsSearchModalOpen(true)}
                    className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-500 px-4 py-2 font-semibold text-white shadow-lg transition-all hover:shadow-cyan-500/50 hover:scale-105"
                >
                    <Plus className="h-5 w-5" />
                    Search & Add Coin
                </button>
            </div>

            {/* Coins Table */}
            <div className="mb-6">
                <MarketOperationsPanel />
            </div>

            <div className="w-full">
                <CoinsTable key={refreshKey} />
            </div>

            {/* Search Modal */}
            <SearchCoinModal
                isOpen={isSearchModalOpen}
                onClose={() => setIsSearchModalOpen(false)}
                onCoinAdded={handleCoinAdded}
            />
        </main>
    );
}
