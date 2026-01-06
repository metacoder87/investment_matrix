"use client";

import { useEffect, useRef, useState, useCallback } from "react";
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
} from "lightweight-charts";

interface CandlestickChartProps {
    symbol: string;
    exchange?: string;
    timeframe?: string;
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
    exchange = "coinbase",
    timeframe = "1m",
}: CandlestickChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
    const [activeTimeframe, setActiveTimeframe] = useState(timeframe);

    const timeframeOptions = ["1m", "5m", "15m", "1h", "4h", "1d"];

    // Normalize symbol for API calls
    const normalizedSymbol = symbol.toUpperCase().replace("/", "-");

    const fetchHistoricalData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

            // Calculate time range based on timeframe
            const end = new Date();
            let hoursBack = 24;
            if (activeTimeframe === "5m") hoursBack = 48;
            else if (activeTimeframe === "15m") hoursBack = 72;
            else if (activeTimeframe === "1h") hoursBack = 24 * 7;
            else if (activeTimeframe === "4h") hoursBack = 24 * 30;
            else if (activeTimeframe === "1d") hoursBack = 24 * 90;

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

            if (!Array.isArray(candles) || candles.length === 0) {
                setError("No historical data available. Try triggering a backfill first.");
                setLoading(false);
                return;
            }

            // Format for lightweight-charts
            const candleData: CandlestickData<Time>[] = candles.map((c) => ({
                time: (new Date(c.timestamp).getTime() / 1000) as Time,
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
            }));

            const volumeData: HistogramData<Time>[] = candles.map((c) => ({
                time: (new Date(c.timestamp).getTime() / 1000) as Time,
                value: c.volume,
                color: c.close >= c.open ? "rgba(34, 211, 238, 0.5)" : "rgba(244, 114, 182, 0.5)",
            }));

            // Sort by time
            candleData.sort((a, b) => (a.time as number) - (b.time as number));
            volumeData.sort((a, b) => (a.time as number) - (b.time as number));

            // Update chart
            // Update chart - Ensure chart is still Mounted (chartRef.current not null)
            if (chartRef.current && candleSeriesRef.current) {
                candleSeriesRef.current.setData(candleData);
            }
            if (chartRef.current && volumeSeriesRef.current) {
                volumeSeriesRef.current.setData(volumeData);
            }

            // Fetch indicators
            await fetchIndicators();

            chartRef.current?.timeScale().fitContent();
            setLastUpdate(new Date());
            setLoading(false);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to fetch data");
            setLoading(false);
        }
    }, [exchange, normalizedSymbol, activeTimeframe]);

    const fetchIndicators = async () => {
        try {
            const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
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
                secondsVisible: activeTimeframe === "1m",
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

        // v5 API: pass series type as first argument
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: "#22d3ee",
            downColor: "#f472b6",
            borderUpColor: "#22d3ee",
            borderDownColor: "#f472b6",
            wickUpColor: "#22d3ee",
            wickDownColor: "#f472b6",
        });
        candleSeriesRef.current = candleSeries;

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
            candleSeriesRef.current = null;
            volumeSeriesRef.current = null;
            bbUpperRef.current = null;
            bbMiddleRef.current = null;
            bbLowerRef.current = null;
        };
    }, [activeTimeframe]);

    // Fetch data when timeframe changes
    useEffect(() => {
        fetchHistoricalData();
    }, [fetchHistoricalData]);

    // WebSocket for live updates
    useEffect(() => {
        const ws = new WebSocket("wss://ws-feed.exchange.coinbase.com");
        const cbSymbol = normalizedSymbol.replace("-USDT", "-USD");

        // Track the current candle being built
        let currentCandle: { time: Time; open: number; high: number; low: number; close: number } | null = null;
        let currentCandleTime: number = 0;

        // Calculate candle bucket time based on timeframe
        const getTimeframeBucket = (timestamp: number): number => {
            const tfMinutes: Record<string, number> = { "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440 };
            const minutes = tfMinutes[activeTimeframe] || 1;
            const bucketSeconds = minutes * 60;
            return Math.floor(timestamp / bucketSeconds) * bucketSeconds;
        };

        ws.onopen = () => {
            ws.send(JSON.stringify({
                type: "subscribe",
                product_ids: [cbSymbol],
                channels: ["ticker"],
            }));
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "ticker" && candleSeriesRef.current) {
                const price = parseFloat(data.price);
                const tickTime = new Date(data.time || Date.now()).getTime() / 1000;
                const bucketTime = getTimeframeBucket(tickTime);

                // If this is a new candle bucket, start fresh
                if (bucketTime !== currentCandleTime) {
                    currentCandleTime = bucketTime;
                    currentCandle = {
                        time: bucketTime as Time,
                        open: price,
                        high: price,
                        low: price,
                        close: price,
                    };
                } else if (currentCandle) {
                    // Update existing candle
                    currentCandle.high = Math.max(currentCandle.high, price);
                    currentCandle.low = Math.min(currentCandle.low, price);
                    currentCandle.close = price;
                }

                if (currentCandle) {
                    candleSeriesRef.current.update(currentCandle);
                }
                setLastUpdate(new Date());
            } else if (data.type === "error") {
                console.debug("Coinbase WS Error (Chart):", data.message);
            }
        };

        ws.onerror = (e) => {
            console.debug("WS Connection Error (Chart)", e);
        };

        return () => ws.close();
    }, [normalizedSymbol, activeTimeframe]);

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
            <div className="flex items-center justify-between">
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
                <div className="text-xs text-gray-500">
                    {loading ? "Loading..." : lastUpdate ? `Updated: ${lastUpdate.toLocaleTimeString()}` : ""}
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
