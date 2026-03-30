import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoinsTable } from "./CoinsTable";
import { resetNavigationMocks, router } from "../../test/mocks/next-navigation";


const coins = [
    {
        id: "bitcoin",
        symbol: "btc",
        name: "Bitcoin",
        image: "/btc.png",
        current_price: 65000,
        market_cap: 1000000,
        price_change_percentage_24h: 2.5,
        analysis: { signal: "BUY", rsi: 55.2, confidence: 0.8 },
    },
    {
        id: "ethereum",
        symbol: "eth",
        name: "Ethereum",
        image: "/eth.png",
        current_price: 3500,
        market_cap: 500000,
        price_change_percentage_24h: -1.5,
        analysis: { signal: "SELL", rsi: 48.3, confidence: 0.6 },
    },
];


describe("CoinsTable", () => {
    beforeEach(() => {
        resetNavigationMocks();
        process.env.NEXT_PUBLIC_API_URL = "http://api.test";
        vi.stubGlobal("fetch", vi.fn());
    });

    it("renders fetched coins and filters by search", async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => coins,
        } as Response);

        render(<CoinsTable />);

        expect(await screen.findByText("Bitcoin")).toBeInTheDocument();
        expect(screen.getByText("Ethereum")).toBeInTheDocument();

        const user = userEvent.setup();
        await user.type(
            screen.getByPlaceholderText(/filter coins/i),
            "eth",
        );

        await waitFor(() => expect(screen.queryByText("Bitcoin")).not.toBeInTheDocument());
        expect(screen.getByText("Ethereum")).toBeInTheDocument();
    });

    it("sorts assets and routes to the market detail page on row click", async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => coins,
        } as Response);

        render(<CoinsTable />);
        await screen.findByText("Bitcoin");

        const user = userEvent.setup();
        await user.click(screen.getByText(/price/i));
        await user.click(screen.getByText(/price/i));

        const links = screen.getAllByRole("link");
        expect(links[0]).toHaveTextContent("ETH");

        await user.click(screen.getByText("Bitcoin").closest("tr") as HTMLTableRowElement);
        expect(router.push).toHaveBeenCalledWith("/market/btc");
    });

    it("shows an error state when the market fetch fails", async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            status: 500,
            json: async () => ({ detail: "boom" }),
        } as Response);

        const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

        render(<CoinsTable />);

        expect(await screen.findByText("Connection Failed")).toBeInTheDocument();
        expect(screen.getByText(/unable to connect to market api/i)).toBeInTheDocument();

        consoleError.mockRestore();
    });
});
