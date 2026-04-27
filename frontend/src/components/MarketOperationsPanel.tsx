"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Database } from "lucide-react";
import { getApiBaseUrl } from "@/utils/api";
import { cn } from "@/utils/cn";

interface OperationStatus {
    celery_queue_depth: number | null;
    status_counts: Record<string, number>;
    exchange_counts?: Record<string, number>;
    ready_by_exchange?: Record<string, number>;
    discovered_by_exchange?: Record<string, number>;
    analyzable_by_exchange?: Record<string, number>;
    active_backfills_by_exchange?: Record<string, number>;
    latest_candle_at: string | null;
    latest_success: {
        exchange: string;
        symbol: string;
        status: string;
        row_count: number;
        latest_candle_at: string | null;
        last_failure_reason: string | null;
    } | null;
    recent_failures: Array<{
        exchange: string;
        symbol: string;
        status: string;
        row_count: number;
        latest_candle_at: string | null;
        last_failure_reason: string | null;
    }>;
}

export function MarketOperationsPanel() {
    const [status, setStatus] = useState<OperationStatus | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        const fetchStatus = async () => {
            try {
                const response = await fetch(`${getApiBaseUrl()}/operations/market`);
                if (!response.ok) throw new Error(`Operations API returned ${response.status}`);
                const data = await response.json();
                if (!cancelled) {
                    setStatus(data);
                    setError(null);
                }
            } catch (err) {
                if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load operations status");
            }
        };
        fetchStatus();
        const interval = window.setInterval(fetchStatus, 30000);
        return () => {
            cancelled = true;
            window.clearInterval(interval);
        };
    }, []);

    if (error) {
        return (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
                <div className="flex items-center gap-2 font-medium">
                    <AlertTriangle className="h-4 w-4" />
                    Market operations unavailable
                </div>
                <p className="mt-1 text-xs text-red-200/70">{error}</p>
            </div>
        );
    }

    if (!status) {
        return <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4 text-sm text-gray-500">Loading market operations...</div>;
    }

    const failed = (status.status_counts.unsupported || 0) + (status.status_counts.backfill_failed || 0);
    const ready = status.ready_by_exchange?.kraken || status.status_counts.ready || 0;
    const pending = status.active_backfills_by_exchange?.kraken || status.status_counts.backfill_pending || 0;
    const discovered = status.discovered_by_exchange?.kraken || status.exchange_counts?.kraken || 0;
    const analyzable = status.analyzable_by_exchange?.kraken || 0;

    return (
        <div className="grid gap-3 rounded-lg border border-white/10 bg-white/[0.02] p-4 md:grid-cols-6">
            <Metric icon={Database} label="Queue" value={status.celery_queue_depth ?? "n/a"} tone={status.celery_queue_depth ? "warn" : "ok"} />
            <Metric icon={Database} label="Kraken markets" value={discovered} tone="info" />
            <Metric icon={CheckCircle2} label="Kraken ready" value={ready} tone="ok" />
            <Metric icon={Activity} label="Analyzable" value={analyzable} tone="info" />
            <Metric icon={Activity} label="Backfills active" value={pending} tone="info" />
            <Metric icon={AlertTriangle} label="Failed/unsupported" value={failed} tone={failed ? "warn" : "ok"} />
            <div className="md:col-span-6">
                <div className="text-xs text-gray-500">
                    Latest candle: {status.latest_candle_at ? new Date(status.latest_candle_at).toLocaleString() : "none"}
                </div>
                {status.recent_failures.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                        {status.recent_failures.slice(0, 5).map((failure) => (
                            <span key={`${failure.exchange}-${failure.symbol}`} className="rounded border border-red-500/20 bg-red-500/10 px-2 py-1 text-[11px] text-red-200" title={failure.last_failure_reason || undefined}>
                                {failure.symbol} - {failure.status}
                            </span>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

function Metric({ icon: Icon, label, value, tone }: { icon: typeof Activity; label: string; value: number | string; tone: "ok" | "warn" | "info" }) {
    return (
        <div className="flex items-center gap-3">
            <div className={cn("flex h-9 w-9 items-center justify-center rounded border", tone === "ok" && "border-green-500/30 bg-green-500/10 text-green-300", tone === "warn" && "border-yellow-500/30 bg-yellow-500/10 text-yellow-300", tone === "info" && "border-cyan-500/30 bg-cyan-500/10 text-cyan-300")}>
                <Icon className="h-4 w-4" />
            </div>
            <div>
                <div className="text-xs text-gray-500">{label}</div>
                <div className="font-mono text-lg font-semibold text-white">{value}</div>
            </div>
        </div>
    );
}
