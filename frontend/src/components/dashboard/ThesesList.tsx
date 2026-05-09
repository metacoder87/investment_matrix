import { ThesisLite } from "@/types/dashboard";
import { cn } from "@/utils/cn";
import { Layers, CheckCircle2, Clock, XCircle, AlertCircle } from "lucide-react";

const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
        case "active":
        case "approved":
            return <CheckCircle2 className="h-4 w-4 text-green-400" />;
        case "pending":
            return <Clock className="h-4 w-4 text-yellow-400" />;
        case "rejected":
            return <XCircle className="h-4 w-4 text-pink-500" />;
        default:
            return <AlertCircle className="h-4 w-4 text-gray-400" />;
    }
};

export function ThesesList({ theses }: { theses: ThesisLite[] }) {
    if (!theses || theses.length === 0) {
        return (
            <div className="neo-card p-5 flex flex-col items-center justify-center min-h-[200px] text-gray-500">
                <Layers className="h-8 w-8 mb-2 opacity-50" />
                <p className="font-mono text-sm uppercase tracking-widest">No Recent Theses</p>
            </div>
        );
    }

    return (
        <div className="neo-card overflow-hidden">
            <header className="border-b border-white/10 px-5 py-3">
                <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                    <Layers className="h-4 w-4 text-purple-400" />
                    Recent AI Theses
                </h2>
            </header>
            <div className="p-5 grid gap-3">
                {theses.map((thesis) => {
                    const confidencePct = Math.round(thesis.confidence * 100);
                    return (
                        <div
                            key={thesis.id}
                            className="flex items-center justify-between rounded border border-white/10 bg-white/5 px-4 py-3 transition hover:border-purple-500/40 hover:bg-purple-500/5"
                        >
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-2">
                                    <span className="font-mono text-sm font-bold text-white">{thesis.symbol}</span>
                                    <span className="text-xs text-gray-500">{thesis.strategy_name}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                    {getStatusIcon(thesis.status)}
                                    <span className="text-[11px] uppercase tracking-wider text-gray-400">
                                        {thesis.status}
                                    </span>
                                </div>
                            </div>

                            <div className="flex items-center gap-6">
                                {thesis.side && (
                                    <span className={cn(
                                        "text-xs font-mono font-bold px-2 py-0.5 rounded",
                                        thesis.side.toLowerCase() === "buy" ? "text-green-400 bg-green-500/10" : "text-pink-500 bg-pink-500/10"
                                    )}>
                                        {thesis.side.toUpperCase()}
                                    </span>
                                )}
                                <div className="flex flex-col items-end gap-1">
                                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Confidence</span>
                                    <div className="flex items-center gap-2">
                                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/10">
                                            <div
                                                className="h-full bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.6)]"
                                                style={{ width: `${confidencePct}%` }}
                                            />
                                        </div>
                                        <span className="font-mono text-xs text-purple-300">{confidencePct}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
