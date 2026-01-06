"use client";

import { useEffect, useRef, useState } from "react";
import {
    createChart,
    ColorType,
    ISeriesApi,
    Time,
    LineData,
    HistogramData,
    LineSeries,
    HistogramSeries,
} from "lightweight-charts";

interface IndicatorPanelProps {
    symbol: string;
}

interface AnalysisData {
    timestamp: string;
    rsi?: number;
    macd?: number;
    macdsignal?: number;
    macdhist?: number;
}

export default function IndicatorPanel({ symbol }: IndicatorPanelProps) {
    const rsiContainerRef = useRef<HTMLDivElement>(null);
    const macdContainerRef = useRef<HTMLDivElement>(null);
    const rsiChartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const macdChartRef = useRef<ReturnType<typeof createChart> | null>(null);

    const [loading, setLoading] = useState(true);
    const [latestRSI, setLatestRSI] = useState<number | null>(null);
    const [latestMACD, setLatestMACD] = useState<{ macd: number; signal: number; hist: number } | null>(null);

    const normalizedSymbol = symbol.toUpperCase().replace("/", "-");

    useEffect(() => {
        if (!rsiContainerRef.current || !macdContainerRef.current) return;

        // RSI Chart
        const rsiChart = createChart(rsiContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#9ca3af",
            },
            width: rsiContainerRef.current.clientWidth,
            height: 120,
            grid: {
                vertLines: { color: "rgba(31, 41, 55, 0.2)" },
                horzLines: { color: "rgba(31, 41, 55, 0.2)" },
            },
            timeScale: { visible: false },
            rightPriceScale: {
                borderColor: "rgba(31, 41, 55, 0.8)",
            },
        });

        // v5 API: pass series type as first argument
        const rsiSeries = rsiChart.addSeries(LineSeries, {
            color: "#a855f7",
            lineWidth: 2,
            priceLineVisible: false,
        });

        // Add RSI overbought/oversold lines
        const rsiChart70 = rsiChart.addSeries(LineSeries, {
            color: "rgba(255, 100, 100, 0.5)",
            lineWidth: 1,
            lineStyle: 2,
            priceLineVisible: false,
        });
        const rsiChart30 = rsiChart.addSeries(LineSeries, {
            color: "rgba(100, 255, 100, 0.5)",
            lineWidth: 1,
            lineStyle: 2,
            priceLineVisible: false,
        });

        rsiChartRef.current = rsiChart;

        // MACD Chart
        const macdChart = createChart(macdContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#9ca3af",
            },
            width: macdContainerRef.current.clientWidth,
            height: 120,
            grid: {
                vertLines: { color: "rgba(31, 41, 55, 0.2)" },
                horzLines: { color: "rgba(31, 41, 55, 0.2)" },
            },
            timeScale: { visible: false },
            rightPriceScale: {
                borderColor: "rgba(31, 41, 55, 0.8)",
            },
        });

        const macdLine = macdChart.addSeries(LineSeries, {
            color: "#3b82f6",
            lineWidth: 2,
            priceLineVisible: false,
        });
        const signalLine = macdChart.addSeries(LineSeries, {
            color: "#f97316",
            lineWidth: 2,
            priceLineVisible: false,
        });
        const histogramSeries = macdChart.addSeries(HistogramSeries, {
            color: "#22d3ee",
            priceLineVisible: false,
        });

        macdChartRef.current = macdChart;

        // Fetch data
        const fetchData = async () => {
            try {
                const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
                const response = await fetch(`${baseUrl}/coin/${normalizedSymbol}/analysis`);

                if (!response.ok) {
                    setLoading(false);
                    return;
                }

                const json = await response.json();
                const data: AnalysisData[] = Array.isArray(json) ? json : (Array.isArray(json.data) ? json.data : []);
                // const calculatedAt = !Array.isArray(json) ? json.calculated_at : null;

                if (!data || data.length === 0) {
                    setLoading(false);
                    return;
                }

                // Process RSI data
                const rsiData: LineData<Time>[] = [];
                const line70: LineData<Time>[] = [];
                const line30: LineData<Time>[] = [];

                // Process MACD data
                const macdData: LineData<Time>[] = [];
                const signalData: LineData<Time>[] = [];
                const histData: HistogramData<Time>[] = [];

                data.forEach((row) => {
                    const time = (new Date(row.timestamp).getTime() / 1000) as Time;

                    if (row.rsi != null) {
                        rsiData.push({ time, value: row.rsi });
                        line70.push({ time, value: 70 });
                        line30.push({ time, value: 30 });
                    }

                    if (row.macd != null) {
                        macdData.push({ time, value: row.macd });
                    }
                    if (row.macdsignal != null) {
                        signalData.push({ time, value: row.macdsignal });
                    }
                    if (row.macdhist != null) {
                        histData.push({
                            time,
                            value: row.macdhist,
                            color: row.macdhist >= 0 ? "rgba(34, 211, 238, 0.7)" : "rgba(244, 114, 182, 0.7)",
                        });
                    }
                });

                // Set latest values
                const lastRow = data[data.length - 1];
                if (lastRow.rsi != null) setLatestRSI(lastRow.rsi);
                if (lastRow.macd != null && lastRow.macdsignal != null && lastRow.macdhist != null) {
                    setLatestMACD({
                        macd: lastRow.macd,
                        signal: lastRow.macdsignal,
                        hist: lastRow.macdhist,
                    });
                }

                // Update charts
                if (rsiData.length > 0) {
                    rsiSeries.setData(rsiData);
                    rsiChart70.setData(line70);
                    rsiChart30.setData(line30);
                    rsiChart.timeScale().fitContent();
                }

                if (macdData.length > 0) {
                    macdLine.setData(macdData);
                    signalLine.setData(signalData);
                    histogramSeries.setData(histData);
                    macdChart.timeScale().fitContent();
                }

                setLoading(false);
            } catch (err) {
                console.error("Failed to fetch indicator data:", err);
                setLoading(false);
            }
        };

        fetchData();

        const handleResize = () => {
            if (rsiContainerRef.current) {
                rsiChart.applyOptions({ width: rsiContainerRef.current.clientWidth });
            }
            if (macdContainerRef.current) {
                macdChart.applyOptions({ width: macdContainerRef.current.clientWidth });
            }
        };
        window.addEventListener("resize", handleResize);

        return () => {
            window.removeEventListener("resize", handleResize);
            rsiChart.remove();
            macdChart.remove();
        };
    }, [normalizedSymbol]);

    const getRsiColor = (rsi: number) => {
        if (rsi >= 70) return "text-red-400";
        if (rsi <= 30) return "text-green-400";
        return "text-purple-400";
    };

    const getRsiLabel = (rsi: number) => {
        if (rsi >= 70) return "Overbought";
        if (rsi <= 30) return "Oversold";
        return "Neutral";
    };

    return (
        <div className="space-y-4">
            {/* RSI Panel */}
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
                <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-medium text-gray-300">RSI (14)</h3>
                    {latestRSI !== null && (
                        <div className="flex items-center gap-2">
                            <span className={`font-mono text-lg font-bold ${getRsiColor(latestRSI)}`}>
                                {latestRSI.toFixed(1)}
                            </span>
                            <span className={`text-xs ${getRsiColor(latestRSI)}`}>
                                {getRsiLabel(latestRSI)}
                            </span>
                        </div>
                    )}
                </div>
                <div
                    ref={rsiContainerRef}
                    className={`w-full rounded ${loading ? "animate-pulse bg-white/5" : ""}`}
                />
            </div>

            {/* MACD Panel */}
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
                <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-medium text-gray-300">MACD (12, 26, 9)</h3>
                    {latestMACD !== null && (
                        <div className="flex items-center gap-4 text-xs">
                            <span className="text-blue-400">
                                MACD: <span className="font-mono">{latestMACD.macd.toFixed(2)}</span>
                            </span>
                            <span className="text-orange-400">
                                Signal: <span className="font-mono">{latestMACD.signal.toFixed(2)}</span>
                            </span>
                            <span className={latestMACD.hist >= 0 ? "text-cyan-400" : "text-pink-400"}>
                                Hist: <span className="font-mono">{latestMACD.hist.toFixed(2)}</span>
                            </span>
                        </div>
                    )}
                </div>
                <div
                    ref={macdContainerRef}
                    className={`w-full rounded ${loading ? "animate-pulse bg-white/5" : ""}`}
                />
            </div>
        </div>
    );
}
