"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
    Activity,
    Database,
    Bot,
    ChevronLeft,
    ChevronRight,
    FlaskConical,
    LayoutDashboard,
    LineChart,
    LogOut,
    Menu,
    PlayCircle,
    Settings,
    User as UserIcon,
    Wallet,
    X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { cn } from "@/utils/cn";

const navItems = [
    { name: "Dashboard", href: "/", icon: LayoutDashboard },
    { name: "Market", href: "/market", icon: LineChart },
    { name: "Backtests", href: "/backtests", icon: FlaskConical },
    { name: "Paper Trading", href: "/paper", icon: PlayCircle },
    { name: "AI Crew", href: "/crew", icon: Bot },
    { name: "Pipeline", href: "/pipeline", icon: Database },
    { name: "Portfolio", href: "/portfolio", icon: Wallet },
    { name: "Settings", href: "/settings", icon: Settings },
];

const STORAGE_KEY = "ci.sidebar.collapsed";

export function Sidebar() {
    const pathname = usePathname();
    const { user, logout } = useAuth();
    const { isOnline } = useHealthCheck();
    const [isOpen, setIsOpen] = useState(false); // mobile drawer
    const [isCollapsed, setIsCollapsed] = useState(false); // desktop icons-only

    // Restore collapsed preference from localStorage
    useEffect(() => {
        try {
            const stored = window.localStorage.getItem(STORAGE_KEY);
            if (stored === "1") setIsCollapsed(true);
        } catch {
            /* no-op */
        }
    }, []);

    // Persist + dispatch a CSS-var update so the layout grid can react
    useEffect(() => {
        try {
            window.localStorage.setItem(STORAGE_KEY, isCollapsed ? "1" : "0");
        } catch {
            /* no-op */
        }
        const root = document.documentElement;
        root.style.setProperty("--sidebar-w", isCollapsed ? "4.5rem" : "16rem");
    }, [isCollapsed]);

    return (
        <>
            {/* Mobile hamburger */}
            <button
                type="button"
                className="fixed left-4 top-4 z-50 flex h-10 w-10 items-center justify-center rounded-lg border border-primary/30 bg-surface/90 text-primary shadow-neon-cyan backdrop-blur md:hidden"
                onClick={() => setIsOpen((open) => !open)}
                aria-label={isOpen ? "Close navigation" : "Open navigation"}
                aria-expanded={isOpen}
            >
                {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>

            {isOpen && (
                <button
                    type="button"
                    className="fixed inset-0 z-30 bg-black/70 backdrop-blur-sm md:hidden"
                    onClick={() => setIsOpen(false)}
                    aria-label="Close navigation"
                />
            )}

            <aside
                className={cn(
                    "fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-primary/20 bg-surface/90 backdrop-blur-xl transition-[transform,width] duration-200 md:translate-x-0",
                    isCollapsed ? "md:w-[4.5rem]" : "md:w-64",
                    "w-64",
                    isOpen ? "translate-x-0" : "-translate-x-full"
                )}
                aria-label="Primary"
            >
                {/* Brand row */}
                <div className="relative flex h-16 shrink-0 items-center border-b border-primary/15 px-4">
                    <Activity className="h-6 w-6 shrink-0 text-primary drop-shadow-[0_0_6px_rgba(0,245,255,0.55)]" />
                    {!isCollapsed && (
                        <span className="ml-2 truncate font-mono text-lg font-bold tracking-tight text-white">
                            Crypto<span className="text-primary neon-text">Insight</span>
                        </span>
                    )}
                    {/* Desktop collapse toggle */}
                    <button
                        type="button"
                        onClick={() => setIsCollapsed((c) => !c)}
                        className="absolute -right-3 top-1/2 hidden h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-primary/40 bg-surface text-primary shadow-neon-cyan transition hover:bg-primary/10 md:flex"
                        aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                        aria-pressed={isCollapsed}
                    >
                        {isCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
                    </button>
                </div>

                {/* Nav */}
                <nav className="flex-1 overflow-y-auto py-4 scrollbar-thin-cyan">
                    <ul className="space-y-1 px-2">
                        {navItems.map((item) => {
                            const active =
                                item.href === "/"
                                    ? pathname === "/"
                                    : pathname.startsWith(item.href);
                            return (
                                <li key={item.name}>
                                    <Link
                                        href={item.href}
                                        onClick={() => setIsOpen(false)}
                                        title={isCollapsed ? item.name : undefined}
                                        aria-label={item.name}
                                        className={cn(
                                            "group relative flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-colors hover:bg-primary/10 hover:text-primary",
                                            active ? "bg-primary/10 text-primary" : "text-gray-400",
                                            isCollapsed ? "md:justify-center md:px-0" : ""
                                        )}
                                    >
                                        {/* Active glow bar */}
                                        {active && (
                                            <span
                                                aria-hidden
                                                className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r bg-primary shadow-neon-cyan"
                                            />
                                        )}
                                        <item.icon
                                            className={cn(
                                                "h-5 w-5 shrink-0",
                                                isCollapsed ? "md:mr-0" : "mr-3"
                                            )}
                                        />
                                        <span
                                            className={cn(
                                                "truncate",
                                                isCollapsed ? "md:hidden" : ""
                                            )}
                                        >
                                            {item.name}
                                        </span>
                                    </Link>
                                </li>
                            );
                        })}
                    </ul>
                </nav>

                {/* Footer / status */}
                <div
                    className={cn(
                        "border-t border-primary/15 bg-white/5 p-3",
                        isCollapsed ? "md:p-2" : ""
                    )}
                >
                    {user ? (
                        <div
                            className={cn(
                                "flex items-center justify-between gap-2",
                                isCollapsed ? "md:flex-col" : ""
                            )}
                        >
                            <div className="flex items-center gap-3 overflow-hidden">
                                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary shadow-neon-cyan">
                                    <UserIcon size={16} />
                                </div>
                                {!isCollapsed && (
                                    <div className="flex-1 truncate">
                                        <p className="truncate text-sm font-medium text-white">{user.email}</p>
                                        <p className="text-xs text-gray-400">Pro Plan</p>
                                    </div>
                                )}
                            </div>
                            <button
                                onClick={logout}
                                className="text-gray-400 transition-colors hover:text-primary"
                                title="Log Out"
                                aria-label="Log Out"
                            >
                                <LogOut size={18} />
                            </button>
                        </div>
                    ) : isCollapsed ? (
                        <div
                            className={cn(
                                "mx-auto flex h-8 w-8 items-center justify-center rounded-full border",
                                isOnline
                                    ? "border-accent/50 bg-accent/10"
                                    : "border-red-500/40 bg-red-500/10"
                            )}
                            title={isOnline ? "System Online" : "System Offline"}
                            aria-label={isOnline ? "System Online" : "System Offline"}
                        >
                            <span
                                className={cn(
                                    "h-2 w-2 animate-pulse rounded-full",
                                    isOnline ? "bg-accent" : "bg-red-500"
                                )}
                            />
                        </div>
                    ) : (
                        <div
                            className={cn(
                                "rounded-xl border p-4 transition-colors",
                                isOnline
                                    ? "border-primary/20 bg-primary/5"
                                    : "border-red-500/20 bg-red-500/5"
                            )}
                        >
                            <div className="mb-1 flex items-center gap-2">
                                <div
                                    className={cn(
                                        "h-2 w-2 animate-pulse rounded-full",
                                        isOnline ? "bg-green-500" : "bg-red-500"
                                    )}
                                />
                                <p
                                    className={cn(
                                        "text-xs font-semibold",
                                        isOnline ? "text-primary" : "text-red-400"
                                    )}
                                >
                                    {isOnline ? "System Online" : "System Offline"}
                                </p>
                            </div>
                            <p className="text-xs text-gray-400">
                                v1.2.0 - {isOnline ? "Stable" : "Reconnecting..."}
                            </p>
                        </div>
                    )}
                </div>
            </aside>
        </>
    );
}
