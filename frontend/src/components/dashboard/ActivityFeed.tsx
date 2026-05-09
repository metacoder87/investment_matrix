import { TraceEventLite } from "@/types/dashboard";
import { Terminal, Bot } from "lucide-react";
import { cn } from "@/utils/cn";

const getRoleColor = (role: string) => {
    switch (role.toLowerCase()) {
        case "risk_manager":
            return "text-pink-400";
        case "analyst":
            return "text-cyan-400";
        case "portfolio_manager":
            return "text-green-400";
        case "system":
            return "text-purple-400";
        default:
            return "text-gray-400";
    }
};

export function ActivityFeed({ activity }: { activity: TraceEventLite[] }) {
    return (
        <div className="neo-card flex flex-col h-full overflow-hidden">
            <header className="border-b border-white/10 px-5 py-3">
                <h2 className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider text-white">
                    <Terminal className="h-4 w-4 text-cyan-400" />
                    Crew Activity
                </h2>
            </header>
            <div className="flex-1 bg-black/40 p-4 overflow-y-auto font-mono text-xs leading-relaxed space-y-3">
                {(!activity || activity.length === 0) ? (
                    <div className="flex items-center text-gray-600 gap-2">
                        <Bot className="h-4 w-4" />
                        Waiting for crew activity...
                    </div>
                ) : (
                    activity.map((event) => {
                        const time = event.created_at ? new Date(event.created_at).toLocaleTimeString([], { hour12: false }) : "--:--:--";
                        const roleColor = getRoleColor(event.role);
                        
                        return (
                            <div key={event.id} className="flex gap-3">
                                <span className="text-gray-600 shrink-0">[{time}]</span>
                                <div className="flex flex-col">
                                    <div className="flex items-center gap-2">
                                        <span className={cn("font-bold uppercase", roleColor)}>{event.role}</span>
                                        {event.symbol && (
                                            <span className="text-gray-400 px-1.5 py-[1px] bg-white/5 rounded text-[10px]">
                                                {event.symbol}
                                            </span>
                                        )}
                                    </div>
                                    <span className="text-gray-300 mt-0.5 break-words">
                                        {event.public_summary}
                                    </span>
                                </div>
                            </div>
                        );
                    })
                )}
                {/* Blinking cursor effect at the end to simulate terminal */}
                {activity && activity.length > 0 && (
                    <div className="flex gap-3">
                        <span className="text-gray-600 shrink-0">[{new Date().toLocaleTimeString([], { hour12: false })}]</span>
                        <span className="w-2 h-3 bg-cyan-400/80 animate-pulse mt-0.5 inline-block"></span>
                    </div>
                )}
            </div>
        </div>
    );
}
