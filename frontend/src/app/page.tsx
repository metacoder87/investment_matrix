import { CoinsTable } from "@/components/CoinsTable";

export default function Home() {
    return (
        <main className="mx-auto min-h-screen max-w-[1600px] p-4 md:p-8">
            <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div>
                    <h1 className="text-3xl font-semibold text-white">Market Dashboard</h1>
                    <p className="mt-1 text-sm text-gray-500">Kraken-first market readiness, signals, and bot eligibility.</p>
                </div>
                <div className="rounded border border-white/10 bg-white/[0.02] px-3 py-2 font-mono text-xs text-primary">
                    CryptoInsight Terminal v0.1.0
                </div>
            </div>
            <CoinsTable />
        </main>
    );
}
