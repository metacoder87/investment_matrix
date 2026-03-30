import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SearchCoinModal from "./SearchCoinModal";


describe("SearchCoinModal", () => {
    beforeEach(() => {
        process.env.NEXT_PUBLIC_API_URL = "http://api.test";
        vi.useFakeTimers();
        vi.stubGlobal("fetch", vi.fn());
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it("does not render when closed", () => {
        render(<SearchCoinModal isOpen={false} onClose={vi.fn()} onCoinAdded={vi.fn()} />);
        expect(screen.queryByText(/search & add coins/i)).not.toBeInTheDocument();
    });

    it("debounces search and adds a coin successfully", async () => {
        vi.mocked(fetch)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => [
                    { id: "bitcoin", symbol: "btc", name: "Bitcoin", market_cap_rank: 1 },
                ],
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ existed: false }),
            } as Response);

        const onClose = vi.fn();
        const onCoinAdded = vi.fn();
        render(<SearchCoinModal isOpen onClose={onClose} onCoinAdded={onCoinAdded} />);

        await act(async () => {
            fireEvent.change(screen.getByPlaceholderText(/search by name or symbol/i), {
                target: { value: "btc" },
            });
            await vi.advanceTimersByTimeAsync(500);
        });

        expect(screen.getByText("Bitcoin")).toBeInTheDocument();
        expect(fetch).toHaveBeenNthCalledWith(
            1,
            "http://api.test/coins/search?q=btc&limit=15",
        );

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /add/i }));
            await Promise.resolve();
        });

        expect(screen.getByText(/added! backfill queued/i)).toBeInTheDocument();
        await vi.advanceTimersByTimeAsync(1500);

        expect(onCoinAdded).toHaveBeenCalledTimes(1);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("shows an error when search fails", async () => {
        const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
        vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));

        render(<SearchCoinModal isOpen onClose={vi.fn()} onCoinAdded={vi.fn()} />);

        await act(async () => {
            fireEvent.change(screen.getByPlaceholderText(/search by name or symbol/i), {
                target: { value: "btc" },
            });
            await vi.advanceTimersByTimeAsync(500);
        });

        expect(screen.getByText(/search failed\. please try again\./i)).toBeInTheDocument();
        consoleError.mockRestore();
    });
});
