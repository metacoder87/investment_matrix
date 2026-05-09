import React from "react";
import { cn } from "@/utils/cn";

interface PortfolioDonutChartProps {
    cash: number;
    invested: number;
}

export function PortfolioDonutChart({ cash, invested }: PortfolioDonutChartProps) {
    const total = cash + invested;
    const investedPct = total > 0 ? invested / total : 0;
    const cashPct = total > 0 ? cash / total : 0;

    // SVG parameters
    const size = 220;
    const strokeWidth = 24;
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    
    const investedOffset = 0;
    const cashOffset = circumference * investedPct;

    return (
        <div className="flex flex-col items-center justify-center p-6">
            <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
                <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90 transform transition-all duration-1000">
                    <circle
                        cx={size / 2}
                        cy={size / 2}
                        r={radius}
                        fill="transparent"
                        stroke="#1e293b"
                        strokeWidth={strokeWidth}
                    />
                    {total > 0 && (
                        <>
                            <circle
                                cx={size / 2}
                                cy={size / 2}
                                r={radius}
                                fill="transparent"
                                stroke="#f59e0b"
                                strokeWidth={strokeWidth}
                                strokeDasharray={`${circumference * investedPct} ${circumference}`}
                                strokeDashoffset={investedOffset}
                                strokeLinecap="round"
                                className="transition-all duration-1000 ease-out"
                            />
                            <circle
                                cx={size / 2}
                                cy={size / 2}
                                r={radius}
                                fill="transparent"
                                stroke="#4ade80"
                                strokeWidth={strokeWidth}
                                strokeDasharray={`${circumference * cashPct} ${circumference}`}
                                strokeDashoffset={-cashOffset}
                                strokeLinecap="round"
                                className="transition-all duration-1000 ease-out"
                            />
                        </>
                    )}
                </svg>
                <div className="absolute flex flex-col items-center justify-center text-center">
                    <span className="text-xs uppercase tracking-wider text-gray-500">Total</span>
                    <span className="font-mono text-xl font-bold text-white neon-text">
                        ${total.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </span>
                </div>
            </div>
            <div className="mt-8 flex w-full flex-wrap justify-center gap-8 text-sm">
                <div className="flex items-center gap-3">
                    <span className="h-3.5 w-3.5 rounded-full bg-amber-500 shadow-[0_0_10px_rgba(245,158,11,0.6)]" />
                    <div className="flex flex-col">
                        <span className="text-xs text-gray-400">Invested ({Math.round(investedPct * 100)}%)</span>
                        <span className="font-mono font-medium text-amber-100">${invested.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <span className="h-3.5 w-3.5 rounded-full bg-green-400 shadow-[0_0_10px_rgba(74,222,128,0.6)]" />
                    <div className="flex flex-col">
                        <span className="text-xs text-gray-400">Cash ({Math.round(cashPct * 100)}%)</span>
                        <span className="font-mono font-medium text-green-100">${cash.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
