"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, ColorType, ISeriesApi, Time } from "lightweight-charts";

interface ChartPoint {
    time: string; // ISO string
    value: number;
}

interface MarketChartProps {
    data: ChartPoint[];
    color?: string; // Hex color for positive/negative reference
}

export default function MarketChart({ data, color = "#22d3ee" }: MarketChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

    // Dynamic color based on trend if not strictly provided
    const isPositive = data.length > 1 ? data[data.length - 1].value >= data[0].value : true;
    const chartColor = isPositive ? "#22d3ee" : "#f472b6"; // Cyan vs Pink/Red

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#9ca3af",
            },
            width: chartContainerRef.current.clientWidth,
            height: 480, // slightly taller for better view
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
                mode: 1, // CrosshairMode.Normal (to match type system, using int 1)
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

        const areaSeries = chart.addAreaSeries({
            lineColor: chartColor,
            topColor: isPositive ? "rgba(34, 211, 238, 0.4)" : "rgba(244, 114, 182, 0.4)",
            bottomColor: isPositive ? "rgba(34, 211, 238, 0.0)" : "rgba(244, 114, 182, 0.0)",
            lineWidth: 2,
        });

        seriesRef.current = areaSeries;
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
            seriesRef.current = null;
        };
    }, []); // Init chart once

    // Update data separately
    useEffect(() => {
        if (!seriesRef.current || !chartRef.current || data.length === 0) return;

        // Map data to Lightweight Charts format
        const formattedData = data.map((d) => ({
            time: (new Date(d.time).getTime() / 1000) as Time,
            value: d.value,
        }));

        // Sort just in case API returns unsorted
        formattedData.sort((a, b) => (a.time as number) - (b.time as number));

        // Remove duplicates
        const uniqueData = formattedData.filter((item, index, self) =>
            index === self.findIndex((t) => (
                t.time === item.time
            ))
        );

        try {
            seriesRef.current.setData(uniqueData);
            chartRef.current?.timeScale().fitContent();

            // Update styling if trend changes
            seriesRef.current.applyOptions({
                lineColor: chartColor,
                topColor: isPositive ? "rgba(34, 211, 238, 0.4)" : "rgba(244, 114, 182, 0.4)",
                bottomColor: isPositive ? "rgba(34, 211, 238, 0.0)" : "rgba(244, 114, 182, 0.0)",
            });
        } catch (e) {
            // Chart likely disposed
            console.warn("Chart update failed (likely disposed)", e);
        }

    }, [data, chartColor, isPositive]);

    if (data.length === 0) {
        return (
            <div className="flex h-[400px] w-full items-center justify-center rounded-xl border border-white/5 bg-white/5 text-gray-500 backdrop-blur-sm">
                Waiting for market data... (Tick updates required)
            </div>
        );
    }

    return (
        <div
            ref={chartContainerRef}
            className="relative w-full overflow-hidden rounded-xl border border-white/10 bg-black/40 shadow-2xl backdrop-blur-md"
        />
    );
}
