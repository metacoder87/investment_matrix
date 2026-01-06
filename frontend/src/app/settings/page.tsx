"use client";

import { useState, useEffect } from "react";

export default function SettingsPage() {
    const [apiUrl, setApiUrl] = useState("");

    useEffect(() => {
        setApiUrl(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api");
    }, []);

    return (
        <main className="p-8 max-w-4xl mx-auto">
            <h1 className="text-3xl font-bold mb-8 text-primary">Settings</h1>

            <div className="space-y-8">
                <section className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <h2 className="text-xl font-semibold mb-4 border-b border-white/10 pb-2">Connection</h2>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm text-gray-400 mb-2">Backend API URL</label>
                            <input
                                type="text"
                                value={apiUrl}
                                readOnly
                                className="w-full bg-black/40 border border-white/10 rounded px-4 py-2 text-gray-300 font-mono text-sm"
                            />
                            <p className="text-xs text-gray-500 mt-2">Configured via environment variables.</p>
                        </div>
                    </div>
                </section>

                <section className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <h2 className="text-xl font-semibold mb-4 border-b border-white/10 pb-2">Appearance</h2>
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="font-medium">Dark Mode</div>
                            <div className="text-sm text-gray-400">Always enabled for that cyberpunk feel.</div>
                        </div>
                        <div className="h-6 w-11 bg-primary rounded-full relative">
                            <div className="absolute right-1 top-1 h-4 w-4 bg-white rounded-full shadow-sm" />
                        </div>
                    </div>
                </section>

                <section className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <h2 className="text-xl font-semibold mb-4 border-b border-white/10 pb-2">Data</h2>
                    <div className="flex items-center gap-4">
                        <button
                            onClick={async () => {
                                if (!confirm("Are you sure? This will clear all cached market data.")) return;
                                try {
                                    const res = await fetch(`${apiUrl}/system/cache/clear`, { method: "POST" });
                                    if (res.ok) alert("Cache cleared successfully!");
                                    else alert("Failed to clear cache.");
                                } catch (e) {
                                    console.error(e);
                                    alert("Error clearing cache.");
                                }
                            }}
                            className="px-4 py-2 border border-red-500/50 text-red-400 rounded hover:bg-red-500/10 transition-colors"
                        >
                            Clear Local Cache
                        </button>
                    </div>
                </section>
            </div>
        </main>
    );
}
