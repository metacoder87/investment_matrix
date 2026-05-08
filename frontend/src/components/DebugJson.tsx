"use client";

import { useState } from "react";
import { Terminal } from "lucide-react";
import { cn } from "@/utils/cn";

interface DebugJsonProps {
    /** Arbitrary value (object, array, string) to be JSON.stringified behind the toggle. */
    value: unknown;
    /** Optional label for the toggle button. Defaults to "View Debug". */
    label?: string;
    className?: string;
    /** Max height (CSS) of the JSON viewer when open. */
    maxHeight?: string;
}

/**
 * A compact "View Debug" button that reveals the raw JSON for a value.
 * Used to hide noisy diagnostic payloads (model prompts, trace evidence,
 * downloaded-model metadata) behind a single click.
 */
export function DebugJson({ value, label = "View Debug", className, maxHeight = "16rem" }: DebugJsonProps) {
    const [open, setOpen] = useState(false);
    const empty =
        value === null ||
        value === undefined ||
        (typeof value === "object" && value !== null && Object.keys(value as Record<string, unknown>).length === 0);

    return (
        <div className={cn("space-y-2", className)}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    "inline-flex items-center gap-2 rounded border border-primary/30 bg-primary/5 px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-primary transition hover:bg-primary/10",
                    empty && "opacity-60"
                )}
                disabled={empty}
                aria-expanded={open}
            >
                <Terminal className="h-3.5 w-3.5" />
                {empty ? "No debug data" : open ? "Hide Debug" : label}
            </button>
            {open && !empty && (
                <pre
                    className="overflow-auto rounded border border-primary/20 bg-black/70 p-3 font-mono text-[11px] leading-relaxed text-gray-200 scrollbar-thin-cyan"
                    style={{ maxHeight }}
                >
                    {JSON.stringify(value, null, 2)}
                </pre>
            )}
        </div>
    );
}

export default DebugJson;
