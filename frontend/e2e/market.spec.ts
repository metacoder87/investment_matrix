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

    await page.route("**/api/coins", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
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
            ]),
        });
    });

    await page.goto("/market");

    await expect(page.getByRole("heading", { name: /market overview/i })).toBeVisible();
    await expect(page.getByText("Bitcoin")).toBeVisible();
    await expect(page.getByText("trader@example.com").first()).toBeVisible();

    await page.getByPlaceholder(/filter coins/i).fill("eth");
    await expect(page.getByText("Ethereum")).toBeVisible();
    await expect(page.getByText("Bitcoin")).toHaveCount(0);
});
