"use client";

import { useEffect, useRef } from "react";

interface MatrixRainProps {
    /** Opacity of the rain layer, 0..1. Defaults to a subtle 0.13. */
    opacity?: number;
    /** Hex color (without alpha) for the glyph stroke. Defaults to neon green. */
    color?: string;
    /** Approximate column width in CSS pixels. Smaller = denser rain. */
    columnWidth?: number;
    /** Frame interval in ms (lower = faster rain). */
    frameMs?: number;
}

/**
 * Fixed-position HTML5 Canvas implementation of the classic "Matrix" digital
 * rain. Drawn with very low opacity so foreground text remains readable.
 *
 * Notes:
 * - Uses a single requestAnimationFrame loop, throttled by `frameMs`.
 * - Honors prefers-reduced-motion (renders a static frame and stops).
 * - Disposes resources on unmount.
 */
export function MatrixRain({
    opacity = 0.13,
    color = "#39ff14",
    columnWidth = 16,
    frameMs = 55,
}: MatrixRainProps) {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        const glyphs =
            "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789ABCDEF$+*/=<>".split("");

        let columns = 0;
        let drops: number[] = [];
        let dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));

        const resize = () => {
            const w = window.innerWidth;
            const h = window.innerHeight;
            dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
            canvas.width = Math.floor(w * dpr);
            canvas.height = Math.floor(h * dpr);
            canvas.style.width = `${w}px`;
            canvas.style.height = `${h}px`;
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.scale(dpr, dpr);
            columns = Math.ceil(w / columnWidth);
            drops = new Array(columns).fill(0).map(() => Math.floor(Math.random() * (h / columnWidth)));
            // Reset background to solid black before painting so the first frame doesn't flash
            ctx.fillStyle = "rgba(5, 1, 13, 1)";
            ctx.fillRect(0, 0, w, h);
        };

        let lastFrame = 0;
        let animationId = 0;
        let stopped = false;

        const draw = (now: number) => {
            if (stopped) return;
            if (now - lastFrame >= frameMs) {
                lastFrame = now;
                const w = window.innerWidth;
                const h = window.innerHeight;

                // Translucent black overlay creates the trailing-fade effect
                ctx.fillStyle = "rgba(5, 1, 13, 0.08)";
                ctx.fillRect(0, 0, w, h);

                ctx.font = `${columnWidth}px ui-monospace, SFMono-Regular, monospace`;
                ctx.fillStyle = color;
                ctx.shadowColor = color;
                ctx.shadowBlur = 6;

                for (let i = 0; i < drops.length; i++) {
                    const text = glyphs[Math.floor(Math.random() * glyphs.length)];
                    const x = i * columnWidth;
                    const y = drops[i] * columnWidth;
                    ctx.fillText(text, x, y);

                    if (y > h && Math.random() > 0.975) {
                        drops[i] = 0;
                    } else {
                        drops[i] += 1;
                    }
                }
                ctx.shadowBlur = 0;
            }
            animationId = window.requestAnimationFrame(draw);
        };

        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        resize();
        if (!reduced) {
            animationId = window.requestAnimationFrame(draw);
        }

        const handleResize = () => resize();
        window.addEventListener("resize", handleResize);

        return () => {
            stopped = true;
            window.cancelAnimationFrame(animationId);
            window.removeEventListener("resize", handleResize);
        };
    }, [color, columnWidth, frameMs]);

    return (
        <canvas
            ref={canvasRef}
            aria-hidden="true"
            className="matrix-rain-bg"
            style={{ opacity }}
        />
    );
}

export default MatrixRain;
