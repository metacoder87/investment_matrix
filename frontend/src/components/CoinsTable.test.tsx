import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoinsTable } from "./CoinsTable";
import { resetNavigationMocks, router } from "../../test/mocks/next-navigation";

const assets = [
    {
        id: "kraken:BTC-USD",
        exchange: "kraken",
        symbol: "BTC-USD",
        ccxt_symbol: "BTC/USD",
        base: "BTC",
        quote: "USD",
        name: "Bitcoin",
        image: "/btc.png",
        current_price: 65000,
        market_cap: 1000000,
        price_change_percentage_24h: 2.5,
        bot_eligible: true,
        is_analyzable: true,
        analysis: { signal: "BUY", rsi: 55.2, confidence: 0.8 },
        data_status: { status: "ready", reason: null, exchange: "kraken", symbol: "BTC-USD", row_count: 60, latest_candle_at: "2026-01-01T00:00:00Z", latest_age_seconds: 60 },
    },
    {
        id: "kraken:ETH-USD",
        exchange: "kraken",
        symbol: "ETH-USD",
        ccxt_symbol: "ETH/USD",
        base: "ETH",
        quote: "USD",
        name: "Ethereum",
        image: "/eth.png",
        current_price: 3500,
        market_cap: 500000,
        price_change_percentage_24h: -1.5,
        bot_eligible: true,
        is_analyzable: true,
        analysis: { signal: "SELL", rsi: 48.3, confidence: 0.6 },
        data_status: { status: "ready", reason: null, exchange: "kraken", symbol: "ETH-USD", row_count: 60, latest_candle_at: "2026-01-01T00:00:00Z", latest_age_seconds: 120 },
    },
    {
        id: "kraken:USDC-USD",
        exchange: "kraken",
        symbol: "USDC-USD",
        ccxt_symbol: "USDC/USD",
        base: "USDC",
        quote: "USD",
        name: "USDC",
        image: "/usdc.png",
        current_price: 1,
        market_cap: 100000,
        price_change_percentage_24h: 0.01,
        bot_eligible: false,
        is_analyzable: false,
        analysis: {},
        data_status: { status: "not_applicable", reason: "Stablecoin signals are disabled by default.", exchange: "kraken", symbol: "USDC-USD", row_count: 0, latest_candle_at: null, latest_age_seconds: null },
    },
];

function response(items = assets) {
    return {
        items,
        total: items.length,
        limit: 500,
        offset: 0,
        counts: {
            total: items.length,
            analyzable: items.filter((item) => item.is_analyzable).length,
            ready: items.filter((item) => item.data_status.status === "ready").length,
            statuses: items.reduce<Record<string, number>>((counts, item) => {
                counts[item.data_status.status] = (counts[item.data_status.status] || 0) + 1;
                return counts;
            }, {}),
        },
    };
}

function mockMarketFetch() {
    vi.mocked(fetch).mockImplementation(async (input) => {
        const url = String(input);
        const filtered = url.includes("search=eth")
            ? [assets[1]]
            : url.includes("scope=ready")
                ? assets.slice(0, 2)
                : assets;
        return { ok: true, json: async () => response(filtered) } as Response;
    });
}

describe("CoinsTable", () => {
    beforeEach(() => {
        resetNavigationMocks();
        process.env.NEXT_PUBLIC_API_URL = "http://api.test";
        vi.stubGlobal("fetch", vi.fn());
    });

    it("renders ready and full Kraken universe tables", async () => {
        mockMarketFetch();

        render(<CoinsTable />);

        expect(await screen.findByText("Ready + Signals")).toBeInTheDocument();
        expect(screen.getByText("Full Kraken Universe")).toBeInTheDocument();
        expect(screen.getAllByText("BTC-USD").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Backfill Kraken").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Not applicable").length).toBeGreaterThan(0);
    });

    it("searches server-side and routes to the market detail page on row click", async () => {
        mockMarketFetch();

        render(<CoinsTable />);
        await screen.findAllByText("BTC-USD");

        const user = userEvent.setup();
        await user.type(screen.getByPlaceholderText(/filter assets/i), "eth");

        await waitFor(() => {
            expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("search=eth"))).toBe(true);
        });

        await user.click(screen.getAllByText("ETH-USD")[0]);
        expect(router.push).toHaveBeenCalledWith("/market/eth-usd");
    });

    it("shows an error state when the market fetch fails", async () => {
        vi.mocked(fetch)
            .mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: "boom" }) } as Response)
            .mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: "boom" }) } as Response);

        const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

        render(<CoinsTable />);

        expect(await screen.findAllByText("Unable to load market assets.")).toHaveLength(2);

        consoleError.mockRestore();
    });
});
