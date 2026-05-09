import { Position } from "@/types/dashboard";
import { cn } from "@/utils/cn";
import { ArrowUpRight, ArrowDownRight, Target } from "lucide-react";

export function PositionsTable({ positions }: { positions: Position[] }) {
    if (!positions || positions.length === 0) {
        return (
            <div className="neo-card p-5 flex flex-col items-center justify-center min-h-[200px] text-gray-500">
                <Target className="h-8 w-8 mb-2 opacity-50" />
                <p className="font-mono text-sm uppercase tracking-widest">No Open Positions</p>
            </div>
        );
    }

    return (
        <div className="neo-card overflow-hidden">
            <header className="border-b border-white/10 px-5 py-3">
                <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                    <Target className="h-4 w-4 text-cyan-400" />
                    Active Positions
                </h2>
            </header>
            <div className="overflow-x-auto">
                <table className="w-full text-left font-mono text-sm">
                    <thead className="bg-white/5 text-[11px] uppercase tracking-wider text-gray-400">
                        <tr>
                            <th className="px-5 py-3 font-medium">Asset</th>
                            <th className="px-5 py-3 font-medium">Side</th>
                            <th className="px-5 py-3 text-right font-medium">Size</th>
                            <th className="px-5 py-3 text-right font-medium">Entry</th>
                            <th className="px-5 py-3 text-right font-medium">Current</th>
                            <th className="px-5 py-3 text-right font-medium">Unrealized P&L</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {positions.map((pos) => {
                            const isLong = pos.side.toLowerCase() === "buy" || pos.side.toLowerCase() === "long";
                            const isProfit = pos.unrealized_pnl >= 0;
                            const PnlIcon = isProfit ? ArrowUpRight : ArrowDownRight;

                            return (
                                <tr key={`${pos.exchange}-${pos.symbol}`} className="transition-colors hover:bg-white/5">
                                    <td className="px-5 py-3 text-white font-semibold">
                                        {pos.symbol}
                                    </td>
                                    <td className="px-5 py-3">
                                        <span className={cn(
                                            "inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-widest",
                                            isLong ? "bg-green-500/10 text-green-400 border border-green-500/20" : "bg-red-500/10 text-red-400 border border-red-500/20"
                                        )}>
                                            {isLong ? "LONG" : "SHORT"}
                                        </span>
                                    </td>
                                    <td className="px-5 py-3 text-right text-gray-300">
                                        {pos.quantity}
                                    </td>
                                    <td className="px-5 py-3 text-right text-gray-300">
                                        ${pos.avg_entry_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
                                    </td>
                                    <td className="px-5 py-3 text-right text-gray-300">
                                        ${pos.last_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
                                    </td>
                                    <td className="px-5 py-3 text-right">
                                        <div className={cn(
                                            "flex items-center justify-end gap-1",
                                            isProfit ? "text-green-400" : "text-pink-500"
                                        )}>
                                            <PnlIcon className="h-3 w-3" />
                                            <span>
                                                ${Math.abs(pos.unrealized_pnl).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                            </span>
                                            <span className="text-[10px] opacity-70 ml-1">
                                                ({(pos.return_pct * 100).toFixed(2)}%)
                                            </span>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
