"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
    createChart,
    ColorType,
    ISeriesApi,
    Time,
    CandlestickData,
    LineData,
    HistogramData,
    CrosshairMode,
    CandlestickSeries,
    LineSeries,
    HistogramSeries,
    AreaSeries,
} from "lightweight-charts";
import { getApiBaseUrl } from "@/utils/api";

interface CandlestickChartProps {
    symbol: string;
    exchange?: string;
    timeframe?: string;
    /**
     * Optional live tick to drive the in-progress candle. When provided the
     * chart will NOT open its own Coinbase WebSocket — useful when a parent
     * component (e.g. the coin-details page) already owns a ticker stream.
     */
    lastTick?: { price: number; time: string | number } | null;
}

interface OHLCV {
    timestamp: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

export default function CandlestickChart({
    symbol,
    exchange = "auto",
    timeframe = "1h",
    lastTick = null,
}: CandlestickChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const seriesRefs = useRef({
        candlestick: null as ISeriesApi<"Candlestick"> | null,
        line: null as ISeriesApi<"Line"> | null,
        area: null as ISeriesApi<"Area"> | null,
    });
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
    const [activeTimeframe, setActiveTimeframe] = useState(timeframe);
    const [activeViews, setActiveViews] = useState<Record<string, boolean>>({
        candlestick: true,
        line: false,
        area: false,
    });
    const [rawCandles, setRawCandles] = useState<OHLCV[]>([]);

    // Mirror activeTimeframe into a ref so the WS handler can read the
    // current value without forcing the WS effect to be torn down and
    // re-opened every time the user clicks a timeframe pill.
    const activeTimeframeRef = useRef(activeTimeframe);
    useEffect(() => {
        activeTimeframeRef.current = activeTimeframe;
    }, [activeTimeframe]);

    const timeframeOptions = ["1m", "5m", "15m", "1h", "4h", "1d"];

    // Normalize symbol for API calls
    const normalizedSymbol = symbol.toUpperCase().replace("/", "-");

    const fetchHistoricalData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const baseUrl = getApiBaseUrl();

            // Calculate time range based on timeframe.
            // Each window targets ~300-1500 bars so the user gets plenty of
            // candles while staying under the backend's max_points cap.
            const end = new Date();
            let hoursBack = 24;             // 1m  → 24h  (1,440 bars)
            if (activeTimeframe === "5m") hoursBack = 24 * 7;       // 7d   (2,016 bars)
            else if (activeTimeframe === "15m") hoursBack = 24 * 14; // 14d (1,344 bars)
            else if (activeTimeframe === "1h") hoursBack = 24 * 30;  // 30d (720 bars)
            else if (activeTimeframe === "4h") hoursBack = 24 * 90;  // 90d (540 bars)
            else if (activeTimeframe === "1d") hoursBack = 24 * 365; // 365d (365 bars)

            const start = new Date(end.getTime() - hoursBack * 60 * 60 * 1000);

            const response = await fetch(
                `${baseUrl}/market/candles/${exchange}/${normalizedSymbol}?` +
                `start=${start.toISOString()}&end=${end.toISOString()}&timeframe=${activeTimeframe}&max_points=2000`
            );

            if (!response.ok) {
                throw new Error(`Failed to fetch data: ${response.status}`);
            }

            const data = await response.json();
            const candles: OHLCV[] = data.candles || data;
            const backfillQueued = Boolean(data?.backfill?.queued);

            if (!Array.isArray(candles) || candles.length === 0) {
                setError(
                    backfillQueued
                        ? "Backfill queued. Refresh in a moment."
                        : "No historical data available. Try triggering a backfill first."
                );
                setLoading(false);
                return;
            }

            // Save raw candles for view switching
            setRawCandles(candles);

            // Format for lightweight-charts
            const formatCandle = (c: OHLCV) => ({ time: (new Date(c.timestamp).getTime() / 1000) as Time, open: c.open, high: c.high, low: c.low, close: c.close });
            const formatValue = (c: OHLCV) => ({ time: (new Date(c.timestamp).getTime() / 1000) as Time, value: c.close });

            const candleData = candles.map(formatCandle).sort((a, b) => (a.time as number) - (b.time as number));
            const valueData = candles.map(formatValue).sort((a, b) => (a.time as number) - (b.time as number));

            const volumeData: HistogramData<Time>[] = candles.map((c) => ({
                time: (new Date(c.timestamp).getTime() / 1000) as Time,
                value: c.volume,
                color: c.close >= c.open ? "rgba(34, 211, 238, 0.5)" : "rgba(244, 114, 182, 0.5)",
            }));
            volumeData.sort((a, b) => (a.time as number) - (b.time as number));

            // Update chart - Ensure chart is still Mounted (chartRef.current not null)
            if (chartRef.current) {
                if (seriesRefs.current.candlestick) seriesRefs.current.candlestick.setData(candleData);
                if (seriesRefs.current.line) seriesRefs.current.line.setData(valueData);
                if (seriesRefs.current.area) seriesRefs.current.area.setData(valueData);
                
                if (volumeSeriesRef.current) volumeSeriesRef.current.setData(volumeData);
            }

            // Fetch indicators
            await fetchIndicators();

            if (chartRef.current && candles.length > 0) {
                const totalBars = candles.length;
                // Show the 33 most recent candlesticks by default
                const barsToShow = Math.min(33, totalBars);
                chartRef.current.timeScale().setVisibleLogicalRange({
                    from: Math.max(0, totalBars - barsToShow),
                    to: totalBars + 2, // small padding on the right
                });
            } else {
                chartRef.current?.timeScale().fitContent();
            }
            setLastUpdate(new Date());
            setLoading(false);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to fetch data");
            setLoading(false);
        }
    }, [exchange, normalizedSymbol, activeTimeframe]);

    const fetchIndicators = async () => {
        try {
            const baseUrl = getApiBaseUrl();
            const response = await fetch(`${baseUrl}/coin/${normalizedSymbol}/analysis`);

            if (!response.ok) return;

            const json = await response.json();
            const analysisData = Array.isArray(json) ? json : (Array.isArray(json.data) ? json.data : []);

            if (!analysisData || analysisData.length === 0) return;

            // Extract Bollinger Bands
            const bbUpperData: LineData<Time>[] = [];
            const bbMiddleData: LineData<Time>[] = [];
            const bbLowerData: LineData<Time>[] = [];

            analysisData.forEach((row: any) => {
                if (row.timestamp && row.bbands_upper != null) {
                    const time = (new Date(row.timestamp).getTime() / 1000) as Time;
                    bbUpperData.push({ time, value: row.bbands_upper });
                    bbMiddleData.push({ time, value: row.bbands_middle });
                    bbLowerData.push({ time, value: row.bbands_lower });
                }
            });

            if (chartRef.current && bbUpperRef.current && bbUpperData.length > 0) {
                bbUpperRef.current.setData(bbUpperData);
            }
            if (chartRef.current && bbMiddleRef.current && bbMiddleData.length > 0) {
                bbMiddleRef.current.setData(bbMiddleData);
            }
            if (chartRef.current && bbLowerRef.current && bbLowerData.length > 0) {
                bbLowerRef.current.setData(bbLowerData);
            }
        } catch (err) {
            console.warn("Failed to fetch indicators:", err);
        }
    };

    // Initialize chart
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#9ca3af",
            },
            width: chartContainerRef.current.clientWidth,
            height: 500,
            grid: {
                vertLines: { color: "rgba(31, 41, 55, 0.4)" },
                horzLines: { color: "rgba(31, 41, 55, 0.4)" },
            },
            timeScale: {
                borderColor: "rgba(31, 41, 55, 0.8)",
                timeVisible: true,
                secondsVisible: false,
            },
            rightPriceScale: {
                borderColor: "rgba(31, 41, 55, 0.8)",
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    width: 1,
                    color: "rgba(255, 255, 255, 0.4)",
                    style: 3,
                },
                horzLine: {
                    width: 1,
                    color: "rgba(255, 255, 255, 0.4)",
                    style: 3,
                },
            },
        });

        // Series are added via activeViews useEffect

        // Volume series
        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: "#26a69a",
            priceFormat: { type: "volume" },
            priceScaleId: "",
        });
        volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.85, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;

        // Bollinger Bands
        bbUpperRef.current = chart.addSeries(LineSeries, {
            color: "rgba(255, 200, 0, 0.5)",
            lineWidth: 1,
            lineStyle: 2,
        });

        bbMiddleRef.current = chart.addSeries(LineSeries, {
            color: "rgba(255, 200, 0, 0.8)",
            lineWidth: 1,
        });

        bbLowerRef.current = chart.addSeries(LineSeries, {
            color: "rgba(255, 200, 0, 0.5)",
            lineWidth: 1,
            lineStyle: 2,
        });

        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener("resize", handleResize);

        return () => {
            window.removeEventListener("resize", handleResize);
            chart.remove();
            chartRef.current = null;
            seriesRefs.current.candlestick = null;
            seriesRefs.current.line = null;
            seriesRefs.current.area = null;
            volumeSeriesRef.current = null;
            bbUpperRef.current = null;
            bbMiddleRef.current = null;
            bbLowerRef.current = null;
        };
        // Chart instance is created once per mount. Switching timeframe used
        // to tear this down and rebuild, causing visible flicker. Now we only
        // re-fetch data and update timeScale options below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Update timeScale options when timeframe changes — without rebuilding chart.
    useEffect(() => {
        const chart = chartRef.current;
        if (!chart) return;
        chart.applyOptions({
            timeScale: {
                timeVisible: true,
                secondsVisible: activeTimeframe === "1m",
            },
        });
    }, [activeTimeframe]);

    // Fetch data when timeframe or chart type changes
    useEffect(() => {
        fetchHistoricalData();
    }, [fetchHistoricalData]);

    // Handle toggling chart types
    useEffect(() => {
        if (!chartRef.current) return;
        const chart = chartRef.current;

        const syncSeries = (
            key: "candlestick" | "line" | "area",
            active: boolean,
            createFn: () => ISeriesApi<any>,
            formatFn: (c: OHLCV) => any
        ) => {
            if (active && !seriesRefs.current[key]) {
                const newSeries = createFn();
                seriesRefs.current[key] = newSeries as any;
                if (rawCandles.length > 0) {
                    newSeries.setData(rawCandles.map(formatFn).sort((a, b) => (a.time as number) - (b.time as number)));
                }
            } else if (!active && seriesRefs.current[key]) {
                chart.removeSeries(seriesRefs.current[key]!);
                seriesRefs.current[key] = null;
            }
        };

        syncSeries(
            "candlestick",
            activeViews.candlestick,
            () => chart.addSeries(CandlestickSeries, {
                upColor: "#22d3ee", downColor: "#f472b6",
                borderUpColor: "#22d3ee", borderDownColor: "#f472b6",
                wickUpColor: "#22d3ee", wickDownColor: "#f472b6",
            }),
            (c) => ({ time: (new Date(c.timestamp).getTime() / 1000) as Time, open: c.open, high: c.high, low: c.low, close: c.close })
        );

        syncSeries(
            "line",
            activeViews.line,
            () => chart.addSeries(LineSeries, { color: "#22d3ee", lineWidth: 2, crosshairMarkerVisible: true, crosshairMarkerRadius: 4 }),
            (c) => ({ time: (new Date(c.timestamp).getTime() / 1000) as Time, value: c.close })
        );

        syncSeries(
            "area",
            activeViews.area,
            () => chart.addSeries(AreaSeries, { lineColor: "#22d3ee", topColor: "rgba(34, 211, 238, 0.4)", bottomColor: "rgba(34, 211, 238, 0.0)", lineWidth: 2, crosshairMarkerVisible: true, crosshairMarkerRadius: 4 }),
            (c) => ({ time: (new Date(c.timestamp).getTime() / 1000) as Time, value: c.close })
        );
    }, [activeViews, rawCandles]);

    // Live-candle accumulator (shared between WS-driven and prop-driven modes).
    const liveCandleRef = useRef<{
        time: Time;
        open: number;
        high: number;
        low: number;
        close: number;
        bucket: number;
    } | null>(null);

    const tfMinutes: Record<string, number> = useMemo(
        () => ({ "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440 }),
        []
    );

    const ingestTick = useCallback((price: number, tickTimeSec: number) => {
        const tf = activeTimeframeRef.current;
        const minutes = tfMinutes[tf] || 1;
        const bucketSeconds = minutes * 60;
        const bucket = Math.floor(tickTimeSec / bucketSeconds) * bucketSeconds;

        const live = liveCandleRef.current;
        if (!live || live.bucket !== bucket) {
            liveCandleRef.current = {
                time: bucket as Time,
                open: price,
                high: price,
                low: price,
                close: price,
                bucket,
            };
        } else {
            live.high = Math.max(live.high, price);
            live.low = Math.min(live.low, price);
            live.close = price;
        }
        const next = liveCandleRef.current;
        if (next) {
            if (seriesRefs.current.candlestick) {
                seriesRefs.current.candlestick.update({ time: next.time, open: next.open, high: next.high, low: next.low, close: next.close });
            }
            if (seriesRefs.current.line) {
                seriesRefs.current.line.update({ time: next.time, value: next.close });
            }
            if (seriesRefs.current.area) {
                seriesRefs.current.area.update({ time: next.time, value: next.close });
            }
        }
        setLastUpdate(new Date());
    }, [tfMinutes]);

    // Mode A: parent supplies live ticks via the `lastTick` prop. Skip WS.
    useEffect(() => {
        if (!lastTick) return;
        const tickTimeSec =
            typeof lastTick.time === "number"
                ? lastTick.time
                : new Date(lastTick.time).getTime() / 1000;
        const price = Number(lastTick.price);
        if (!Number.isFinite(price)) return;
        ingestTick(price, tickTimeSec);
    }, [lastTick, ingestTick]);

    // Mode B: open our own Coinbase WS with exponential-backoff reconnect.
    // Only runs when the parent did NOT pass `lastTick` (avoiding duplicate
    // sockets when used from coin-details page).
    useEffect(() => {
        if (lastTick !== null && lastTick !== undefined) return;

        const cbSymbol = normalizedSymbol.replace("-USDT", "-USD");
        let ws: WebSocket | null = null;
        let reconnectTimer: number | null = null;
        let attempt = 0;
        let cancelled = false;

        const connect = () => {
            if (cancelled) return;
            ws = new WebSocket("wss://ws-feed.exchange.coinbase.com");

            ws.onopen = () => {
                attempt = 0; // reset backoff on successful open
                ws?.send(JSON.stringify({
                    type: "subscribe",
                    product_ids: [cbSymbol],
                    channels: ["ticker"],
                }));
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === "ticker") {
                    const price = parseFloat(data.price);
                    const tickTime = new Date(data.time || Date.now()).getTime() / 1000;
                    if (!Number.isFinite(price)) return;
                    ingestTick(price, tickTime);
                } else if (data.type === "error") {
                    console.debug("Coinbase WS Error (Chart):", data.message);
                }
            };

            ws.onerror = (error) => {
                console.warn("[CandlestickChart] WebSocket error:", error);
            };

            ws.onclose = (event) => {
                if (cancelled) return;
                // Exponential backoff: 1s, 2s, 4s, ... capped at 30s.
                const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
                attempt += 1;
                console.warn(
                    `[CandlestickChart] WS closed (code ${event.code}); reconnecting in ${delay}ms`
                );
                reconnectTimer = window.setTimeout(connect, delay);
            };
        };

        connect();

        return () => {
            cancelled = true;
            if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
            try {
                ws?.close();
            } catch {
                /* no-op */
            }
        };
    }, [normalizedSymbol, lastTick, ingestTick]);

    if (error) {
        return (
            <div className="flex h-[500px] w-full items-center justify-center rounded-xl border border-red-500/30 bg-red-500/10 text-red-400">
                <div className="text-center">
                    <p className="mb-2 font-medium">{error}</p>
                    <button
                        onClick={fetchHistoricalData}
                        className="rounded bg-red-500/20 px-4 py-2 text-sm hover:bg-red-500/30"
                    >
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-2">
            {/* Timeframe Selector */}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex gap-1">
                    {timeframeOptions.map((tf) => (
                        <button
                            key={tf}
                            onClick={() => setActiveTimeframe(tf)}
                            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${activeTimeframe === tf
                                ? "bg-cyan-500/20 text-cyan-400"
                                : "text-gray-500 hover:text-white"
                                }`}
                        >
                            {tf.toUpperCase()}
                        </button>
                    ))}
                </div>
                {/* Chart Type Selector */}
                <div className="flex gap-1 rounded bg-white/5 p-1">
                    {(["candlestick", "line", "area"] as const).map((type) => (
                        <button
                            key={type}
                            onClick={() => setActiveViews(prev => ({ ...prev, [type]: !prev[type as keyof typeof prev] }))}
                            className={`rounded px-3 py-1 text-xs font-medium capitalize transition-colors ${activeViews[type]
                                ? "bg-white/10 text-white shadow"
                                : "text-gray-500 hover:text-white"
                                }`}
                        >
                            {type === "candlestick" ? "Candles" : type}
                        </button>
                    ))}
                </div>
                <div className="flex items-center gap-3">
                    <button
                        type="button"
                        onClick={() => chartRef.current?.timeScale().fitContent()}
                        className="rounded border border-white/10 px-2 py-1 text-xs text-gray-400 transition hover:border-cyan-500/40 hover:text-cyan-300"
                        title="Fit all loaded candles to the chart"
                    >
                        Fit all
                    </button>
                    <div className="text-xs text-gray-500">
                        {loading ? "Loading..." : lastUpdate ? `Updated: ${lastUpdate.toLocaleTimeString()}` : ""}
                    </div>
                </div>
            </div>

            {/* Chart Container */}
            <div
                ref={chartContainerRef}
                className={`relative w-full overflow-hidden rounded-xl border border-white/10 bg-black/40 shadow-2xl backdrop-blur-md ${loading ? "animate-pulse" : ""
                    }`}
            />

            {/* Legend */}
            <div className="flex gap-4 text-xs text-gray-500">
                <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-cyan-400" /> Bullish
                </span>
                <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-pink-400" /> Bearish
                </span>
                <span className="flex items-center gap-1">
                    <span className="h-2 w-4 border-t border-dashed border-yellow-500" /> Bollinger Bands
                </span>
            </div>
        </div>
    );
}
