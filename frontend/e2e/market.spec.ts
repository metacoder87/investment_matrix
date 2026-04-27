import { expect, test } from "@playwright/test";


test("renders the market view for an authenticated user", async ({ context, page }) => {
    await context.addCookies([
        {
            name: "auth_token",
            value: "test-token",
            domain: "127.0.0.1",
            path: "/",
        },
    ]);

    await page.route("**/api/auth/me", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                id: 1,
                email: "trader@example.com",
                full_name: "Trader",
            }),
        });
    });

    await page.route("**/api/health", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ status: "ok" }),
        });
    });

    await page.route("**/api/operations/market", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                celery_queue_depth: 0,
                status_counts: { ready: 2 },
                exchange_counts: { kraken: 500 },
                ready_by_exchange: { kraken: 2 },
                discovered_by_exchange: { kraken: 500 },
                analyzable_by_exchange: { kraken: 450 },
                active_backfills_by_exchange: { kraken: 0 },
                latest_candle_at: "2026-01-01T00:00:00Z",
                latest_success: null,
                recent_failures: [],
            }),
        });
    });

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
    ];

    await page.route("**/api/market/assets**", async (route) => {
        const url = new URL(route.request().url());
        const filtered = url.searchParams.get("search") ? assets.filter((asset) => asset.symbol.includes("ETH")) : assets;
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                items: filtered,
                total: filtered.length,
                limit: 500,
                offset: 0,
                counts: { total: filtered.length, analyzable: filtered.length, ready: filtered.length, statuses: { ready: filtered.length } },
            }),
        });
    });

    await page.goto("/market");

    await expect(page.getByRole("heading", { name: /market overview/i })).toBeVisible();
    await expect(page.getByText("BTC-USD").first()).toBeVisible();
    await expect(page.getByText("trader@example.com").first()).toBeVisible();

    await page.getByPlaceholder(/filter assets/i).fill("eth");
    await expect(page.getByText("ETH-USD").first()).toBeVisible();
    await expect(page.getByText("BTC-USD")).toHaveCount(0);
});
