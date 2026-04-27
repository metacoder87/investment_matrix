"use client";

import { AlertTriangle, RefreshCcw } from "lucide-react";

export default function CrewError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
    return (
        <main className="mx-auto max-w-3xl p-6 md:p-10">
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-6 text-red-100">
                <AlertTriangle className="mb-4 h-8 w-8" />
                <h1 className="text-2xl font-semibold text-white">AI Crew dashboard hit a client-side error</h1>
                <p className="mt-3 text-sm text-red-100/80">
                    The page caught the failure instead of crashing the app. Refreshing the dashboard will reload the Crew state from the backend.
                </p>
                <pre className="mt-4 max-h-40 overflow-auto rounded bg-black/40 p-3 text-xs text-red-100/80">
                    {error.message || "Unknown dashboard error."}
                </pre>
                <button
                    onClick={reset}
                    className="mt-5 inline-flex items-center gap-2 rounded border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-50 hover:bg-red-500/20"
                >
                    <RefreshCcw className="h-4 w-4" />
                    Reload AI Crew
                </button>
            </div>
        </main>
    );
}
