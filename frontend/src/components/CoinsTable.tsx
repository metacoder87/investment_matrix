"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, RefreshCcw, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/utils/cn";
import { formatCompactNumber, formatPrice } from "@/utils/format";
import { getApiBaseUrl } from "@/utils/api";

interface MarketAsset {
    id: string;
    exchange: string;
    symbol: string;
    ccxt_symbol: string;
    base: string;
    quote: string;
    name: string;
    image: string;
    current_price: number | null;
    market_cap: number | null;
    price_change_percentage_24h: number | null;
    bot_eligible: boolean;
    is_analyzable: boolean;
    analysis?: {
        signal?: string | null;
        rsi?: number | null;
        confidence?: number | null;
        reasons?: string[];
    };
    data_status?: {
        status: string;
        reason: string | null;
        exchange: string;
        symbol: string;
        row_count: number;
        latest_candle_at: string | null;
        latest_age_seconds?: number | null;
    };
}

interface MarketAssetResponse {
    items: MarketAsset[];
    total: number;
    limit: number;
    offset: number;
    counts: {
        total: number;
        analyzable: number;
        ready: number;
        statuses: Record<string, number>;
    };
}

type Scope = "ready" | "all";
type SortKey = "symbol" | "current_price" | "analysis.rsi" | "analysis.signal" | "data_status.row_count" | "price_change_percentage_24h" | "market_cap";

const emptyResponse: MarketAssetResponse = {
    items: [],
    total: 0,
    limit: 500,
    offset: 0,
    counts: { total: 0, analyzable: 0, ready: 0, statuses: {} },
};

export function CoinsTable() {
    const [exchange, setExchange] = useState("kraken");
    const [pageSize, setPageSize] = useState(500);
    const [search, setSearch] = useState("");
    const [offset, setOffset] = useState(0);
    const [refreshKey, setRefreshKey] = useState(0);
    const [operationNotice, setOperationNotice] = useState<string | null>(null);
    const [operationError, setOperationError] = useState<string | null>(null);

    useEffect(() => {
        setOffset(0);
    }, [exchange, pageSize, search]);

    const backfillKraken = async () => {
        setOperationNotice(null);
        setOperationError(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/operations/market/backfill-kraken?limit=${pageSize}`, {
                method: "POST",
                credentials: "include",
            });
            if (!response.ok) throw new Error(`Backfill request failed with ${response.status}`);
            const payload = await response.json();
            setOperationNotice(`${payload.queued || 0} Kraken backfills queued.`);
            setRefreshKey((value) => value + 1);
        } catch (err) {
            setOperationError(err instanceof Error ? err.message : "Unable to queue Kraken backfills.");
        }
    };

    const syncKraken = async () => {
        setOperationNotice(null);
        setOperationError(null);
        try {
            const response = await fetch(`${getApiBaseUrl()}/operations/market/sync-kraken`, {
                method: "POST",
                credentials: "include",
            });
            if (!response.ok) throw new Error(`Market sync failed with ${response.status}`);
            const payload = await response.json();
            setOperationNotice(`${payload.stored || payload.seen || 0} Kraken markets synced.`);
            setRefreshKey((value) => value + 1);
        } catch (err) {
            setOperationError(err instanceof Error ? err.message : "Unable to sync Kraken markets.");
        }
    };

    return (
        <div className="space-y-5">
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                    <div className="flex flex-1 flex-col gap-3 md:flex-row md:items-center">
                        <label className="relative block w-full max-w-xl">
                            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-500" />
                            <input
                                type="text"
                                placeholder="Filter assets by symbol or name"
                                className="w-full rounded border border-white/10 bg-black/40 px-9 py-2 text-sm text-white outline-none focus:border-cyan-400"
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                            />
                        </label>
                        <select
                            value={exchange}
                            onChange={(event) => setExchange(event.target.value)}
                            className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-gray-200"
                            aria-label="Market data exchange"
                        >
                            <option value="kraken">Kraken</option>
                            <option value="coinbase">Coinbase</option>
                            <option value="binance">Binance</option>
                        </select>
                        <select
                            value={pageSize}
                            onChange={(event) => setPageSize(Number(event.target.value))}
                            className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-gray-200"
                            aria-label="Market page size"
                        >
                            <option value={100}>100 rows</option>
                            <option value={500}>500 rows</option>
                            <option value={1000}>1000 rows</option>
                            <option value={5000}>All loaded</option>
                        </select>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <button
                            onClick={syncKraken}
                            className="inline-flex items-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-200 hover:bg-white/10"
                        >
                            <RefreshCcw className="h-4 w-4" />
                            Sync Kraken
                        </button>
                        <button
                            onClick={backfillKraken}
                            className="inline-flex items-center gap-2 rounded border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20"
                        >
                            <RefreshCcw className="h-4 w-4" />
                            Backfill Kraken
                        </button>
                    </div>
                </div>
                {operationNotice ? <div className="mt-3 text-xs text-cyan-200">{operationNotice}</div> : null}
                {operationError ? <div className="mt-3 text-xs text-red-200">{operationError}</div> : null}
            </div>

            <MarketAssetSection
                title="Ready + Signals"
                subtitle="Analyzable assets with enough Kraken candles for signals and bot eligibility."
                scope="ready"
                exchange={exchange}
                pageSize={pageSize}
                offset={offset}
                search={search}
                refreshKey={refreshKey}
                onOffsetChange={setOffset}
            />
            <MarketAssetSection
                title="Full Kraken Universe"
                subtitle="Discovered USD, USDT, and USDC spot markets with pipeline status and backfill readiness."
                scope="all"
                exchange={exchange}
                pageSize={pageSize}
                offset={offset}
                search={search}
                refreshKey={refreshKey}
                onOffsetChange={setOffset}
            />
        </div>
    );
}

function MarketAssetSection({
    title,
    subtitle,
    scope,
    exchange,
    pageSize,
    offset,
    search,
    refreshKey,
    onOffsetChange,
}: {
    title: string;
    subtitle: string;
    scope: Scope;
    exchange: string;
    pageSize: number;
    offset: number;
    search: string;
    refreshKey: number;
    onOffsetChange: (value: number) => void;
}) {
    const router = useRouter();
    const [payload, setPayload] = useState<MarketAssetResponse>(emptyResponse);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [sortConfig, setSortConfig] = useState<{ key: SortKey; direction: "asc" | "desc" } | null>(scope === "ready" ? { key: "analysis.signal", direction: "desc" } : null);
    const parentRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        let cancelled = false;
        const params = new URLSearchParams({
            exchange,
            scope,
            limit: String(pageSize),
            offset: String(offset),
        });
        if (search.trim()) params.set("search", search.trim());
        setLoading(true);
        setError(null);
        fetch(`${getApiBaseUrl()}/market/assets?${params.toString()}`, { credentials: "include" })
            .then((response) => {
                if (!response.ok) throw new Error(`Market API returned ${response.status}`);
                return response.json();
            })
            .then((data: MarketAssetResponse) => {
                if (!cancelled) {
                    setPayload(data);
                    setLoading(false);
                }
            })
            .catch((err) => {
                if (!cancelled) {
                    console.error("Failed to fetch market assets", err);
                    setError("Unable to load market assets.");
                    setLoading(false);
                }
            });
        return () => {
            cancelled = true;
        };
    }, [exchange, scope, pageSize, offset, search, refreshKey]);

    const rows = useMemo(() => {
        const items = [...payload.items];
        if (!sortConfig) return items;
        return items.sort((a, b) => compareAsset(a, b, sortConfig.key, sortConfig.direction));
    }, [payload.items, sortConfig]);

    const rowVirtualizer = useVirtualizer({
        count: rows.length,
        getScrollElement: () => parentRef.current,
        initialRect: { width: 1180, height: 520 },
        estimateSize: () => 56,
        overscan: 16,
    });
    const virtualItems = rowVirtualizer.getVirtualItems();
    const visibleItems = virtualItems.length
        ? virtualItems
        : rows.map((_, index) => ({ index, key: index, size: 56, start: index * 56 }));
    const virtualHeight = virtualItems.length ? rowVirtualizer.getTotalSize() : rows.length * 56;

    const nextOffset = Math.min(payload.total, offset + pageSize);
    const canPrevious = offset > 0;
    const canNext = offset + pageSize < payload.total;

    const handleSort = (key: SortKey) => {
        setSortConfig((current) => ({
            key,
            direction: current?.key === key && current.direction === "desc" ? "asc" : "desc",
        }));
    };

    return (
        <section className="overflow-hidden rounded-lg border border-white/10 bg-white/[0.02]">
            <div className="flex flex-col gap-3 border-b border-white/10 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                    <h2 className="text-lg font-semibold text-white">{title}</h2>
                    <p className="mt-1 text-xs text-gray-500">{subtitle}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
                    <StatusSummary counts={payload.counts} />
                    <span>{payload.total.toLocaleString()} total</span>
                    <button
                        disabled={!canPrevious}
                        onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
                        className="rounded border border-white/10 px-2 py-1 disabled:opacity-40"
                    >
                        Prev
                    </button>
                    <span>
                        {payload.total === 0 ? 0 : offset + 1}-{nextOffset}
                    </span>
                    <button
                        disabled={!canNext}
                        onClick={() => onOffsetChange(offset + pageSize)}
                        className="rounded border border-white/10 px-2 py-1 disabled:opacity-40"
                    >
                        Next
                    </button>
                </div>
            </div>

            <div className="overflow-x-auto">
                <div className="min-w-[1180px]">
                    <div className="grid grid-cols-[210px_110px_90px_140px_150px_100px_110px_120px_120px] border-b border-white/10 bg-white/[0.04] px-4 py-2 text-xs uppercase text-gray-500">
                        <HeaderButton label="Asset" onClick={() => handleSort("symbol")} />
                        <HeaderButton label="Price" align="right" onClick={() => handleSort("current_price")} />
                        <HeaderButton label="RSI" align="right" onClick={() => handleSort("analysis.rsi")} />
                        <HeaderButton label="Signal" align="center" onClick={() => handleSort("analysis.signal")} />
                        <HeaderButton label="Data" align="center" onClick={() => handleSort("data_status.row_count")} />
                        <div className="text-center">Eligible</div>
                        <HeaderButton label="24h" align="right" onClick={() => handleSort("price_change_percentage_24h")} />
                        <HeaderButton label="Market cap" align="right" onClick={() => handleSort("market_cap")} />
                        <div className="text-right">Age</div>
                    </div>

                    {loading ? (
                        <div className="p-8 text-center text-sm text-gray-500">Loading {title.toLowerCase()}...</div>
                    ) : error ? (
                        <div className="p-8 text-center text-sm text-red-200">{error}</div>
                    ) : rows.length === 0 ? (
                        <div className="p-8 text-center text-sm text-gray-500">No assets matched this view.</div>
                    ) : (
                        <div ref={parentRef} className="h-[520px] overflow-auto">
                            <div style={{ height: `${virtualHeight}px`, position: "relative" }}>
                                {visibleItems.map((virtualRow) => {
                                    const asset = rows[virtualRow.index];
                                    return (
                                        <div
                                            key={asset.id}
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => router.push(`/market/${asset.symbol.toLowerCase()}`)}
                                            onKeyDown={(event) => {
                                                if (event.key === "Enter") router.push(`/market/${asset.symbol.toLowerCase()}`);
                                            }}
                                            className="grid cursor-pointer grid-cols-[210px_110px_90px_140px_150px_100px_110px_120px_120px] items-center border-b border-white/5 px-4 py-2 text-sm transition-colors hover:bg-white/[0.04]"
                                            style={{
                                                position: "absolute",
                                                top: 0,
                                                left: 0,
                                                width: "100%",
                                                height: `${virtualRow.size}px`,
                                                transform: `translateY(${virtualRow.start}px)`,
                                            }}
                                        >
                                            <AssetCell asset={asset} />
                                            <div className="text-right font-mono text-white">{formatPrice(asset.current_price)}</div>
                                            <div className="text-right font-mono text-gray-300">{asset.analysis?.rsi != null && !isNaN(Number(asset.analysis.rsi)) ? Number(asset.analysis.rsi).toFixed(1) : "-"}</div>
                                            <div className="text-center">{signalBadge(asset)}</div>
                                            <div className="text-center">
                                                <div className="flex flex-col items-center gap-1">
                                                    {statusBadge(asset.data_status?.status, asset.data_status?.reason)}
                                                    <span className="text-[11px] text-gray-500">
                                                        {asset.exchange.toUpperCase()} - {asset.data_status?.row_count || 0} rows
                                                    </span>
                                                </div>
                                            </div>
                                            <div className="text-center">{asset.bot_eligible ? <StatusPill text="Bot ready" tone="green" /> : <StatusPill text="Blocked" tone="gray" />}</div>
                                            <div className={cn("flex items-center justify-end gap-1 font-mono", (asset.price_change_percentage_24h || 0) >= 0 ? "text-green-300" : "text-red-300")}>
                                                {(asset.price_change_percentage_24h || 0) >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                                                {Math.abs(asset.price_change_percentage_24h || 0).toFixed(2)}%
                                            </div>
                                            <div className="text-right font-mono text-gray-400">{formatCompactNumber(asset.market_cap)}</div>
                                            <div className="text-right text-xs text-gray-500">{formatAge(asset.data_status?.latest_age_seconds)}</div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </section>
    );
}

function AssetCell({ asset }: { asset: MarketAsset }) {
    return (
        <div className="flex min-w-0 items-center gap-3">
            {asset.image ? (
                <img src={asset.image} alt={asset.name} className="h-8 w-8 rounded-full" />
            ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-white/5 text-[11px] text-gray-300">
                    {asset.base.slice(0, 3)}
                </div>
            )}
            <div className="min-w-0">
                <div className="truncate font-semibold text-white">{asset.symbol}</div>
                <div className="truncate text-xs text-gray-500">{asset.name} / {asset.quote}</div>
            </div>
        </div>
    );
}

function HeaderButton({ label, align = "left", onClick }: { label: string; align?: "left" | "right" | "center"; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn("text-xs uppercase text-gray-500 transition-colors hover:text-white", align === "right" && "text-right", align === "center" && "text-center")}
        >
            {label}
        </button>
    );
}

function StatusSummary({ counts }: { counts: MarketAssetResponse["counts"] }) {
    return (
        <div className="flex flex-wrap gap-2">
            <StatusPill text={`${counts.ready || 0} ready`} tone="green" />
            <StatusPill text={`${counts.analyzable || 0} analyzable`} tone="cyan" />
            <StatusPill text={`${counts.statuses?.backfill_pending || 0} queued`} tone="yellow" />
        </div>
    );
}

function signalBadge(asset: MarketAsset) {
    const signal = asset.analysis?.signal;
    if (!signal) return statusBadge(asset.data_status?.status, asset.data_status?.reason);
    const value = signal.toUpperCase();
    if (value.includes("STRONG BUY")) return <StatusPill text="Strong buy" tone="green" />;
    if (value.includes("BUY")) return <StatusPill text="Buy" tone="green" />;
    if (value.includes("STRONG SELL")) return <StatusPill text="Strong sell" tone="red" />;
    if (value.includes("SELL")) return <StatusPill text="Sell" tone="red" />;
    return <StatusPill text="Neutral" tone="gray" />;
}

function statusBadge(status: string | null | undefined, reason?: string | null) {
    const key = status || "not_loaded";
    const labels: Record<string, string> = {
        ready: "Ready",
        stale: "Stale",
        warming_up: "Warming up",
        insufficient_data: "Needs candles",
        unsupported_market: "Unsupported",
        unsupported: "Unsupported",
        backfill_pending: "Backfill queued",
        backfill_failed: "Backfill failed",
        not_applicable: "Not applicable",
        not_loaded: "Not loaded",
    };
    const tone = ["ready", "stale"].includes(key)
        ? "green"
        : ["backfill_pending", "warming_up", "insufficient_data"].includes(key)
            ? "cyan"
            : ["unsupported_market", "unsupported", "backfill_failed"].includes(key)
                ? "red"
                : "gray";
    return <StatusPill text={labels[key] || key.replaceAll("_", " ")} tone={tone} title={reason || undefined} />;
}

function StatusPill({ text, tone, title }: { text: string; tone: "green" | "cyan" | "yellow" | "red" | "gray"; title?: string }) {
    return (
        <span
            title={title}
            className={cn(
                "inline-flex whitespace-nowrap rounded border px-2 py-1 text-[11px] font-medium",
                tone === "green" && "border-green-500/30 bg-green-500/10 text-green-200",
                tone === "cyan" && "border-cyan-500/30 bg-cyan-500/10 text-cyan-200",
                tone === "yellow" && "border-yellow-500/30 bg-yellow-500/10 text-yellow-200",
                tone === "red" && "border-red-500/30 bg-red-500/10 text-red-200",
                tone === "gray" && "border-white/10 bg-white/5 text-gray-400",
            )}
        >
            {text}
        </span>
    );
}

function compareAsset(a: MarketAsset, b: MarketAsset, key: SortKey, direction: "asc" | "desc") {
    const aValue = sortableValue(a, key);
    const bValue = sortableValue(b, key);
    if (aValue < bValue) return direction === "asc" ? -1 : 1;
    if (aValue > bValue) return direction === "asc" ? 1 : -1;
    return a.symbol.localeCompare(b.symbol);
}

function sortableValue(asset: MarketAsset, key: SortKey): number | string {
    if (key === "symbol") return asset.symbol;
    if (key === "analysis.rsi") return asset.analysis?.rsi ?? -1;
    if (key === "analysis.signal") return signalScore(asset.analysis?.signal);
    if (key === "data_status.row_count") return asset.data_status?.row_count ?? 0;
    return asset[key] ?? 0;
}

function signalScore(signal: string | null | undefined) {
    if (!signal) return 0;
    const value = signal.toUpperCase();
    if (value.includes("STRONG BUY")) return 5;
    if (value.includes("BUY")) return 4;
    if (value.includes("HOLD")) return 3;
    if (value.includes("NEUTRAL")) return 2.5;
    if (value.includes("SELL")) return 2;
    if (value.includes("STRONG SELL")) return 1;
    return 0;
}

function formatAge(seconds: number | null | undefined) {
    if (seconds === null || seconds === undefined) return "-";
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
}
