import { CoinsTable } from "@/components/CoinsTable";

export default function MarketPage() {
    return (
        <main className="p-8 max-w-7xl mx-auto">
            <h1 className="text-3xl font-bold mb-6 text-primary">Market Overview</h1>
            <div className="w-full">
                <CoinsTable />
            </div>
        </main>
    );
}
