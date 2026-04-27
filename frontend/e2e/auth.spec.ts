import { expect, test } from "@playwright/test";


test("redirects unauthenticated users away from protected routes", async ({ page }) => {
    await page.route("**/api/auth/me", async (route) => {
        await route.fulfill({
            status: 401,
            contentType: "application/json",
            body: JSON.stringify({ detail: "unauthorized" }),
        });
    });

    await page.route("**/api/health", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ status: "ok" }),
        });
    });

    await page.goto("/market");

    await expect(page).toHaveURL(/\/login\?redirect=%2Fmarket/);
    await expect(page.getByRole("heading", { name: /welcome back/i })).toBeVisible();
});

test("confirms cookie session before redirecting after sign in", async ({ page }) => {
    await page.route("**/api/auth/me", async (route) => {
        const cookie = route.request().headers().cookie ?? "";
        if (cookie.includes("auth_token=test-token")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    id: 1,
                    email: "trader@example.com",
                    full_name: "Trader",
                }),
            });
            return;
        }

        await route.fulfill({
            status: 401,
            contentType: "application/json",
            body: JSON.stringify({ detail: "unauthorized" }),
        });
    });

    await page.route("**/api/auth/token", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            headers: {
                "Set-Cookie": "auth_token=test-token; Path=/; SameSite=Lax",
            },
            body: JSON.stringify({ access_token: "header.payload.signature", token_type: "bearer" }),
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
                status_counts: { ready: 1 },
                exchange_counts: { kraken: 1 },
                ready_by_exchange: { kraken: 1 },
                discovered_by_exchange: { kraken: 1 },
                analyzable_by_exchange: { kraken: 1 },
                active_backfills_by_exchange: { kraken: 0 },
                latest_candle_at: "2026-01-01T00:00:00Z",
                latest_success: null,
                recent_failures: [],
            }),
        });
    });

    await page.route("**/api/market/assets**", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                items: [
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
                ],
                total: 1,
                limit: 500,
                offset: 0,
                counts: { total: 1, analyzable: 1, ready: 1, statuses: { ready: 1 } },
            }),
        });
    });

    await page.goto("/login?redirect=%2Fmarket");
    await page.getByPlaceholder("name@example.com").fill("trader@example.com");
    await page.getByPlaceholder("********").fill("hunter2");
    await page.getByRole("button", { name: "Sign In" }).click();

    await expect(page).toHaveURL(/\/market$/);
    await expect(page.getByRole("heading", { name: /market overview/i })).toBeVisible();
    await expect(page.getByText("BTC-USD").first()).toBeVisible();
});
