import Link from "next/link";
import { LayoutDashboard, LineChart, Wallet, Settings, Activity } from "lucide-react";
import { cn } from "@/utils/cn";

const navItems = [
    { name: "Dashboard", href: "/", icon: LayoutDashboard },
    { name: "Market", href: "/market", icon: LineChart },
    { name: "Portfolio", href: "/portfolio", icon: Wallet },
    { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
    return (
        <aside className="fixed left-0 top-0 z-40 h-screen w-64 -translate-x-full border-r border-white/10 bg-surface/80 backdrop-blur-xl transition-transform md:translate-x-0">
            <div className="flex h-16 items-center border-b border-white/10 px-6">
                <Activity className="mr-2 h-6 w-6 text-primary" />
                <span className="text-xl font-bold tracking-tight text-white">
                    Crypto<span className="text-primary">Insight</span>
                </span>
            </div>

            <div className="py-4">
                <ul className="space-y-1 px-3">
                    {navItems.map((item) => (
                        <li key={item.name}>
                            <Link
                                href={item.href}
                                className={cn(
                                    "flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-colors hover:bg-white/5 hover:text-primary",
                                    item.href === "/" ? "bg-white/5 text-primary" : "text-gray-400"
                                )}
                            >
                                <item.icon className="mr-3 h-5 w-5" />
                                {item.name}
                            </Link>
                        </li>
                    ))}
                </ul>
            </div>

            <div className="absolute bottom-4 left-0 w-full px-6">
                <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                    <p className="text-xs font-semibold text-primary">Connected</p>
                    <p className="text-xs text-gray-400">Mainnet • v0.1.0</p>
                </div>
            </div>
        </aside>
    );
}
