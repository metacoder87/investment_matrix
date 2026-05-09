"use client";

import { useAuth } from "@/context/AuthContext";
import { LogOut, User } from "lucide-react";

export function Header() {
    const { user, isAuthenticated, logout, isLoading } = useAuth();

    return (
        <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-white/10 bg-surface/50 px-6 backdrop-blur-md">
            <div />

            <div className="hidden md:flex items-center space-x-4 ml-auto">
                <div className="flex items-center px-3 py-1 rounded-full border border-white/10 bg-white/5">
                    <div className="w-2 h-2 rounded-full bg-green-500 mr-2 animate-pulse"></div>
                    <span className="text-xs font-mono text-gray-300">SYSTEM: ONLINE</span>
                </div>

                {!isLoading && isAuthenticated && user && (
                    <>
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-white/10 bg-white/5">
                            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-cyan-500/20 text-cyan-400">
                                <User className="h-4 w-4" />
                            </div>
                            <div className="flex flex-col">
                                <span className="text-xs font-medium text-white">
                                    {user.full_name || user.email}
                                </span>
                                {user.full_name && (
                                    <span className="text-[10px] text-gray-500">{user.email}</span>
                                )}
                            </div>
                        </div>

                        <button
                            onClick={logout}
                            className="flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-1.5 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/20"
                            title="Logout"
                        >
                            <LogOut className="h-4 w-4" />
                            <span className="hidden lg:inline">Logout</span>
                        </button>
                    </>
                )}
            </div>
        </header>
    );
}
