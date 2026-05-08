"use client";

import { type ReactNode, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/utils/cn";

interface AccordionProps {
    title: string;
    /** Small badge / count rendered next to the title (e.g. "12 events"). */
    summary?: ReactNode;
    /** Right-aligned controls (e.g. View Debug toggle). */
    controls?: ReactNode;
    /** Whether the panel is open by default. */
    defaultOpen?: boolean;
    /** Extra classes for the outer container. */
    className?: string;
    /** Adds the neon-pulse animation when something inside is "active" (e.g. a successful trade). */
    pulse?: boolean;
    children: ReactNode;
}

/**
 * Cyberpunk-styled collapsible panel. Used to wrap dense sections like
 * Decision Log or Downloaded Models so they only show summary data by
 * default and can be expanded on demand.
 */
export function Accordion({
    title,
    summary,
    controls,
    defaultOpen = false,
    className,
    pulse = false,
    children,
}: AccordionProps) {
    const [open, setOpen] = useState(defaultOpen);

    return (
        <section
            className={cn(
                "neo-card",
                pulse && "neo-card-active",
                className
            )}
        >
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-3">
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    aria-expanded={open}
                    className="group flex items-center gap-2 text-left"
                >
                    <ChevronDown
                        className={cn(
                            "h-4 w-4 text-primary transition-transform duration-200",
                            open ? "rotate-0" : "-rotate-90"
                        )}
                    />
                    <h2 className="font-mono text-sm font-semibold uppercase tracking-wider text-white group-hover:text-primary">
                        {title}
                    </h2>
                    {summary !== undefined && summary !== null && (
                        <span className="ml-2 rounded border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary">
                            {summary}
                        </span>
                    )}
                </button>
                {controls && <div className="flex items-center gap-2">{controls}</div>}
            </header>
            <div
                className={cn(
                    "grid transition-[grid-template-rows] duration-200 ease-out",
                    open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                )}
            >
                <div className="overflow-hidden">{children}</div>
            </div>
        </section>
    );
}

export default Accordion;
