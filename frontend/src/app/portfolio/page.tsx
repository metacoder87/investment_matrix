export default function PortfolioPage() {
    return (
        <main className="p-8 max-w-7xl mx-auto">
            <div className="flex items-center gap-3 mb-6">
                <h1 className="text-3xl font-bold text-primary">Portfolio</h1>
                <span className="text-xs font-medium px-2 py-1 bg-yellow-500/20 text-yellow-400 rounded-full">
                    Coming Soon
                </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <div className="text-sm text-gray-400 mb-2">Total Balance</div>
                    <div className="text-3xl font-bold font-mono text-gray-500">---</div>
                    <div className="text-sm text-gray-500 mt-2">Connect to view</div>
                </div>
                <div className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <div className="text-sm text-gray-400 mb-2">Daily PnL</div>
                    <div className="text-3xl font-bold font-mono text-gray-500">---</div>
                </div>
                <div className="rounded-xl border border-white/10 bg-surface/50 p-6 backdrop-blur-sm">
                    <div className="text-sm text-gray-400 mb-2">Open Positions</div>
                    <div className="text-3xl font-bold font-mono text-gray-500">---</div>
                </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-surface/50 overflow-hidden">
                <div className="p-4 border-b border-white/10 bg-white/5">
                    <h2 className="font-semibold">Your Assets</h2>
                </div>
                <div className="p-8 text-center text-gray-400">
                    <p className="mb-2 text-lg">Portfolio tracking requires exchange integration</p>
                    <p className="mb-6 text-sm text-gray-500">This feature is part of Phase 5 (Live Trading). Connect your exchange API keys to enable portfolio tracking.</p>
                    <button className="px-4 py-2 bg-primary/20 text-primary font-bold rounded hover:bg-primary/30 transition-colors border border-primary/30">
                        Connect Wallet / Exchange
                    </button>
                </div>
            </div>
        </main>
    );
}

