export function Header() {
    return (
        <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-white/10 bg-surface/50 px-6 backdrop-blur-md">
            <div className="md:hidden">
                {/* Mobile menu trigger placeholder */}
                <span className="text-gray-400">Menu</span>
            </div>

            <div className="hidden md:flex items-center space-x-4 ml-auto">
                <div className="flex items-center px-3 py-1 rounded-full border border-white/10 bg-white/5">
                    <div className="w-2 h-2 rounded-full bg-green-500 mr-2 animate-pulse"></div>
                    <span className="text-xs font-mono text-gray-300">SYSTEM: ONLINE</span>
                </div>

                <button className="rounded-full bg-primary/10 p-2 text-primary hover:bg-primary/20 transition-colors">
                    <span className="sr-only">Notifications</span>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                    </svg>
                </button>
            </div>
        </header>
    );
}
