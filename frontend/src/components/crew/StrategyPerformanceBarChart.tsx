import React from "react";
import { cn } from "@/utils/cn";

export interface StrategyPerformance {
    strategy_name: string;
    recommendations: number;
    executed: number;
    wins: number;
    losses: number;
    success_rate_pct: number;
}

export function StrategyPerformanceBarChart({ strategies }: { strategies: StrategyPerformance[] }) {
    if (!strategies || strategies.length === 0) {
        return <div className="p-8 text-center text-sm text-gray-500">No strategy data available.</div>;
    }

    const maxExecuted = Math.max(...strategies.map((s) => s.executed), 1);

    return (
        <div className="space-y-6 p-6">
            {strategies.slice(0, 5).map((strategy) => (
                <div key={strategy.strategy_name} className="flex flex-col gap-2">
                    <div className="flex justify-between text-sm">
                        <span className="font-medium text-white">{strategy.strategy_name}</span>
                        <span className="font-mono text-gray-400">
                            {strategy.wins}W / {strategy.losses}L ({strategy.success_rate_pct.toFixed(1)}%)
                        </span>
                    </div>
                    <div className="relative h-3 w-full overflow-hidden rounded bg-white/5">
                        <div
                            className={cn(
                                "absolute left-0 top-0 h-full rounded transition-all duration-1000",
                                strategy.success_rate_pct >= 50 ? "bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.6)]" : "bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.6)]"
                            )}
                            style={{ width: `${(strategy.executed / maxExecuted) * 100}%` }}
                        />
                    </div>
                    <div className="text-xs text-gray-500">
                        {strategy.executed} executed / {strategy.recommendations} recommended
                    </div>
                </div>
            ))}
        </div>
    );
}
