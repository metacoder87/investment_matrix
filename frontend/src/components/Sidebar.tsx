"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
    Activity,
    Database,
    Bot,
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

export function Sidebar() {
    const pathname = usePathname();
    const { user, logout } = useAuth();
    const { isOnline } = useHealthCheck();
    const [isOpen, setIsOpen] = useState(false);

    return (
        <>
            <button
                type="button"
                className="fixed left-4 top-4 z-50 flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-surface/90 text-gray-200 backdrop-blur md:hidden"
                onClick={() => setIsOpen((open) => !open)}
                aria-label={isOpen ? "Close navigation" : "Open navigation"}
                aria-expanded={isOpen}
            >
                {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>

            {isOpen && (
                <button
                    type="button"
                    className="fixed inset-0 z-30 bg-black/60 md:hidden"
                    onClick={() => setIsOpen(false)}
                    aria-label="Close navigation"
                />
            )}

            <aside
                className={cn(
                    "fixed left-0 top-0 z-40 flex h-screen w-64 flex-col border-r border-white/10 bg-surface/95 backdrop-blur-xl transition-transform md:translate-x-0",
                    isOpen ? "translate-x-0" : "-translate-x-full"
                )}
            >
                <div className="flex h-16 shrink-0 items-center border-b border-white/10 px-6">
                    <Activity className="mr-2 h-6 w-6 text-primary" />
                    <span className="text-xl font-bold tracking-tight text-white">
                        Crypto<span className="text-primary">Insight</span>
                    </span>
                </div>

                <div className="flex-1 overflow-y-auto py-4">
                    <ul className="space-y-1 px-3">
                        {navItems.map((item) => (
                            <li key={item.name}>
                                <Link
                                    href={item.href}
                                    onClick={() => setIsOpen(false)}
                                    className={cn(
                                        "flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-colors hover:bg-white/5 hover:text-primary",
                                        item.href === "/"
                                            ? pathname === "/"
                                                ? "bg-white/5 text-primary"
                                                : "text-gray-400"
                                            : pathname.startsWith(item.href)
                                                ? "bg-white/5 text-primary"
                                                : "text-gray-400"
                                    )}
                                >
                                    <item.icon className="mr-3 h-5 w-5" />
                                    {item.name}
                                </Link>
                            </li>
                        ))}
                    </ul>
                </div>

                <div className="border-t border-white/10 bg-white/5 p-4">
                    {user ? (
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3 overflow-hidden">
                                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary">
                                    <UserIcon size={16} />
                                </div>
                                <div className="flex-1 truncate">
                                    <p className="truncate text-sm font-medium text-white">{user.email}</p>
                                    <p className="text-xs text-gray-400">Pro Plan</p>
                                </div>
                            </div>
                            <button
                                onClick={logout}
                                className="text-gray-400 transition-colors hover:text-white"
                                title="Log Out"
                            >
                                <LogOut size={18} />
                            </button>
                        </div>
                    ) : (
                        <div
                            className={cn(
                                "rounded-xl border p-4 transition-colors",
                                isOnline ? "border-primary/20 bg-primary/5" : "border-red-500/20 bg-red-500/5"
                            )}
                        >
                            <div className="mb-1 flex items-center gap-2">
                                <div
                                    className={cn(
                                        "h-2 w-2 animate-pulse rounded-full",
                                        isOnline ? "bg-green-500" : "bg-red-500"
                                    )}
                                />
                                <p className={cn("text-xs font-semibold", isOnline ? "text-primary" : "text-red-400")}>
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
