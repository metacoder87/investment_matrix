"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, LineChart, Wallet, Settings, Activity, Database, FlaskConical, PlayCircle } from "lucide-react";
import { cn } from "@/utils/cn";
import { useHealthCheck } from "@/hooks/useHealthCheck";

const navItems = [
    { name: "Dashboard", href: "/", icon: LayoutDashboard },
    { name: "Market", href: "/market", icon: LineChart },
    { name: "Backtests", href: "/backtests", icon: FlaskConical },
    { name: "Paper Trading", href: "/paper", icon: PlayCircle },
    { name: "Pipeline", href: "/pipeline", icon: Database },
    { name: "Portfolio", href: "/portfolio", icon: Wallet },
    { name: "Settings", href: "/settings", icon: Settings },
];

import { useAuth } from "@/context/AuthContext";
import { LogOut, User as UserIcon } from "lucide-react";

export function Sidebar() {
    const pathname = usePathname();
    const { user, logout } = useAuth();
    const { isOnline } = useHealthCheck();

    return (
        <aside className="fixed left-0 top-0 z-40 h-screen w-64 -translate-x-full border-r border-white/10 bg-surface/80 backdrop-blur-xl transition-transform md:translate-x-0 flex flex-col">
            <div className="flex h-16 items-center border-b border-white/10 px-6 shrink-0">
                <Activity className="mr-2 h-6 w-6 text-primary" />
                <span className="text-xl font-bold tracking-tight text-white">
                    Crypto<span className="text-primary">Insight</span>
                </span>
            </div>

            <div className="py-4 flex-1 overflow-y-auto">
                <ul className="space-y-1 px-3">
                    {navItems.map((item) => (
                        <li key={item.name}>
                            <Link
                                href={item.href}
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

            <div className="p-4 border-t border-white/10 bg-white/5">
                {user ? (
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3 overflow-hidden">
                            <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary shrink-0">
                                <UserIcon size={16} />
                            </div>
                            <div className="flex-1 truncate">
                                <p className="text-sm font-medium text-white truncate">{user.email}</p>
                                <p className="text-xs text-gray-400">Pro Plan</p>
                            </div>
                        </div>
                        <button onClick={logout} className="text-gray-400 hover:text-white transition-colors" title="Log Out">
                            <LogOut size={18} />
                        </button>
                    </div>
                ) : (
                    <div className={cn(
                        "rounded-xl border p-4 transition-colors",
                        isOnline ? "border-primary/20 bg-primary/5" : "border-red-500/20 bg-red-500/5"
                    )}>
                        <div className="flex items-center gap-2 mb-1">
                            <div className={cn("h-2 w-2 rounded-full animate-pulse", isOnline ? "bg-green-500" : "bg-red-500")} />
                            <p className={cn("text-xs font-semibold", isOnline ? "text-primary" : "text-red-400")}>
                                {isOnline ? "System Online" : "System Offline"}
                            </p>
                        </div>
                        <p className="text-xs text-gray-400">v1.2.0 • {isOnline ? "Stable" : "Reconnecting..."}</p>
                    </div>
                )}
            </div>
        </aside>
    );
}
