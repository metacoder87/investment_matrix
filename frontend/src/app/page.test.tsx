import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "./page";

vi.mock("@/context/AuthContext", () => ({
    useAuth: () => ({
        user: { id: 1, email: "trader@example.com", full_name: "Trader" },
        isAuthenticated: true,
        isLoading: false,
        login: vi.fn(),
        logout: vi.fn(),
    }),
}));

function jsonResponse(body: unknown): Response {
    return {
        ok: true,
        json: async () => body,
    } as Response;
}

describe("DashboardPage", () => {
    beforeEach(() => {
        process.env.NEXT_PUBLIC_API_URL = "http://api.test";
        vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url.endsWith("/crew/portfolio/summary")) {
                return jsonResponse({
                    available_bankroll: 7200,
                    cash_balance: 7200,
                    invested_value: 3100,
                    total_equity: 10300,
                    long_exposure: 2400,
                    short_exposure: 700,
                    realized_pnl: 120,
                    unrealized_pnl: 180,
                    all_time_pnl: 300,
                    current_cycle_pnl: 300,
                    drawdown_pct: -1.4,
                    exposure_pct: 30.1,
                    open_positions: 1,
                    sleeve_win_rates: { long: 0.7, short: 0.65 },
                });
            }
            if (url.endsWith("/crew/portfolio/equity")) return jsonResponse([]);
            if (url.endsWith("/crew/portfolio/positions")) return jsonResponse([]);
            if (url.endsWith("/crew/theses")) return jsonResponse([]);
            if (url.endsWith("/crew/activity?limit=5&debug=false")) return jsonResponse([]);
            if (url.endsWith("/portfolio/dashboard")) {
                return jsonResponse({
                    source: "user",
                    portfolio_count: 2,
                    available_bankroll: 0,
                    cash_balance: 0,
                    invested_value: 12000,
                    total_cost: 12000,
                    total_equity: 15000,
                    long_exposure: 15000,
                    short_exposure: 0,
                    realized_pnl: 600,
                    unrealized_pnl: 2400,
                    all_time_pnl: 3000,
                    current_cycle_pnl: 3000,
                    drawdown_pct: 0,
                    exposure_pct: 100,
                    open_positions: 2,
                    sleeve_win_rates: { long: 0, short: 0 },
                    closed_win_rate: 0.5,
                    closed_trade_count: 2,
                    closed_wins: 1,
                    closed_losses: 1,
                    positions: [
                        {
                            symbol: "BTC-USD",
                            exchange: "coinbase",
                            side: "long",
                            quantity: 0.1,
                            avg_entry_price: 70000,
                            last_price: 80000,
                            market_value: 8000,
                            unrealized_pnl: 1000,
                            return_pct: 14.2857,
                        },
                    ],
                    recent_orders: [
                        {
                            id: 11,
                            portfolio_id: 3,
                            portfolio_name: "Manual Alpha",
                            symbol: "BTC-USD",
                            exchange: "coinbase",
                            side: "sell",
                            status: "filled",
                            price: 81000,
                            amount: 0.05,
                            realized_pnl: 600,
                            timestamp: "2026-05-08T12:00:00",
                        },
                    ],
                });
            }
            return jsonResponse({});
        }));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("loads KPI data from the crew portfolio summary endpoint", async () => {
        render(<DashboardPage />);

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith("http://api.test/crew/portfolio/summary", { credentials: "include" });
        });
        expect(fetch).not.toHaveBeenCalledWith("http://api.test/crew/summary", { credentials: "include" });

        expect(await screen.findByText("$7,200")).toBeInTheDocument();
        expect(screen.getByText("67.5%")).toBeInTheDocument();
        expect(screen.getByText("L 70% / S 65%")).toBeInTheDocument();
    });

    it("toggles to user trade dashboard data", async () => {
        const user = userEvent.setup();
        render(<DashboardPage />);

        expect(await screen.findByText("Bankroll")).toBeInTheDocument();
        expect(fetch).not.toHaveBeenCalledWith("http://api.test/portfolio/dashboard", { credentials: "include" });

        await user.click(screen.getByRole("tab", { name: /user trades/i }));

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith("http://api.test/portfolio/dashboard", { credentials: "include" });
        });
        expect(await screen.findByText("Portfolio Value")).toBeInTheDocument();
        expect(screen.getByText("$15,000")).toBeInTheDocument();
        expect(screen.getByText("Closed Win Rate")).toBeInTheDocument();
        expect(screen.getByText("50.0%")).toBeInTheDocument();
        expect(screen.getByText("2 closed trades")).toBeInTheDocument();
        expect(screen.getAllByText("Open Holdings").length).toBeGreaterThan(0);
        expect(screen.getByText("Recent User Trades")).toBeInTheDocument();
        expect(screen.getByText("Manual Alpha")).toBeInTheDocument();
    });
});
