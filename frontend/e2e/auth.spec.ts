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
