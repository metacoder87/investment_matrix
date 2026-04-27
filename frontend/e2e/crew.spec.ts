import { expect, test } from "@playwright/test";


test("renders the autonomous AI trading team dashboard", async ({ context, page }) => {
    await context.addCookies([
        {
            name: "auth_token",
            value: "test-token",
            domain: "127.0.0.1",
            path: "/",
        },
    ]);

    const summary = {
        account_id: 5,
        account_name: "AI Team Bankroll",
        cash_balance: 7200,
        available_bankroll: 7200,
        invested_value: 3100,
        total_equity: 10300,
        realized_pnl: 120,
        unrealized_pnl: 180,
        all_time_pnl: 300,
        current_cycle_pnl: 300,
        drawdown_pct: -1.4,
        exposure_pct: 30.1,
        open_positions: 1,
        reset_count: 2,
        last_reset_at: "2026-01-01T00:00:00Z",
        seconds_since_last_reset: 86400,
        settings: {
            autonomous_enabled: true,
            research_enabled: true,
            trigger_monitor_enabled: true,
            bot_state: "running",
            primary_exchange: "kraken",
            global_crew_enabled: true,
            global_research_enabled: true,
            global_trigger_monitor_enabled: true,
            research_interval_seconds: 1800,
            max_position_pct: 0.35,
            max_daily_loss_pct: 0.1,
            max_open_positions: 12,
            max_trades_per_day: 40,
            bankroll_reset_drawdown_pct: 0.95,
            default_starting_bankroll: 10000,
            trade_cadence_mode: "aggressive_paper",
            ai_paper_account_id: 5,
        },
        positions: [],
        recent_orders: [],
    };

    await page.route("**/api/auth/me", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ id: 1, email: "trader@example.com", full_name: "Trader" }),
        });
    });

    await page.route("**/api/health", async (route) => {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
    });

    await page.route("**/api/crew/runtime", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                enabled: true,
                available: true,
                provider: "ollama",
                base_url: "http://ollama",
                model: "test-model",
                status: "available",
                message: "Ollama runtime is reachable.",
                model_routing: {
                    selected: { default: "test-model", research: null, thesis: "test-model", risk: null, trade: "trade-model" },
                    effective: { default: "test-model", research: "test-model", thesis: "test-model", risk: "test-model", trade: "trade-model" },
                    fallback_model: "test-model",
                },
            }),
        });
    });

    await page.route("**/api/crew/models", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                available: true,
                status: "available",
                message: "Ollama runtime is reachable.",
                provider: "ollama",
                base_url: "http://ollama",
                current_model: "test-model",
                models: [
                    { name: "test-model", model: "test-model", size: 1000, family: "llama", parameter_size: "8B", quantization_level: "Q4", modified_at: "2026-01-01T00:00:00Z" },
                    { name: "trade-model", model: "trade-model", size: 2000, family: "qwen", parameter_size: "14B", quantization_level: "Q4", modified_at: "2026-01-01T00:00:00Z" },
                ],
                routing: {
                    selected: { default: "test-model", research: null, thesis: "test-model", risk: null, trade: "trade-model" },
                    effective: { default: "test-model", research: "test-model", thesis: "test-model", risk: "test-model", trade: "trade-model" },
                    fallback_model: "test-model",
                },
            }),
        });
    });

    await page.route("**/api/crew/model-performance", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    model: "test-model",
                    role: "Thesis Strategist",
                    calls: 4,
                    successes: 3,
                    failures: 1,
                    timeouts: 1,
                    approved: 0,
                    rejected: 0,
                    validation_failures: 0,
                    avg_latency_ms: 1200,
                    theses_created: 2,
                    trades_approved: 0,
                    trades_rejected: 0,
                    success_rate_pct: 75,
                    timeout_rate_pct: 25,
                    latest_status: "timeout",
                    latest_error: "Read timed out.",
                    latest_validation_error: null,
                    last_used_at: "2026-01-01T01:00:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/crew/portfolio/summary", async (route) => {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(summary) });
    });

    await page.route("**/api/crew/portfolio/equity", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                { timestamp: "2026-01-01T00:00:00Z", cash_balance: 10000, invested_value: 0, equity: 10000, drawdown_pct: 0 },
                { timestamp: "2026-01-01T01:00:00Z", cash_balance: 7200, invested_value: 3100, equity: 10300, drawdown_pct: -1.4 },
            ]),
        });
    });

    await page.route("**/api/crew/portfolio/positions", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    id: 1,
                    symbol: "BTC-USD",
                    exchange: "kraken",
                    quantity: 0.04,
                    avg_entry_price: 70000,
                    last_price: 74500,
                    market_value: 2980,
                    cost_basis: 2800,
                    unrealized_pnl: 180,
                    return_pct: 6.42,
                },
            ]),
        });
    });

    await page.route("**/api/crew/portfolio/orders", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    id: 10,
                    symbol: "BTC-USD",
                    exchange: "kraken",
                    side: "buy",
                    status: "filled",
                    price: 70000,
                    quantity: 0.04,
                    fee: 2.8,
                    strategy: "buy_hold",
                    reason: "entry_trigger:1",
                    timestamp: "2026-01-01T01:00:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/crew/strategies/performance", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    strategy_name: "buy_hold",
                    recommendations: 4,
                    executed: 2,
                    blocked: 1,
                    wins: 1,
                    losses: 0,
                    avg_return_pct: 6.42,
                    success_rate_pct: 100,
                    last_used_at: "2026-01-01T01:00:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/crew/theses", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    id: 1,
                    symbol: "BTC-USD",
                    exchange: "kraken",
                    strategy_name: "buy_hold",
                    confidence: 0.84,
                    thesis: "Mocked active thesis with target conditions.",
                    risk_notes: "Paper-only risk.",
                    entry_condition: "at_or_below",
                    entry_target: 70500,
                    take_profit_target: 76000,
                    stop_loss_target: 68000,
                    latest_observed_price: 74500,
                    status: "entry_triggered",
                    expires_at: "2026-01-01T05:00:00Z",
                    triggered_at: "2026-01-01T01:00:00Z",
                    created_at: "2026-01-01T00:30:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/crew/resets", async (route) => {
        if (route.request().method() === "POST") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 3 }) });
            return;
        }
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    id: 2,
                    reset_number: 2,
                    starting_bankroll: 10000,
                    equity_before_reset: 450,
                    drawdown_pct: -95.5,
                    realized_pnl: -9550,
                    reason: "Automatic reset",
                    lessons: "Reduce exposure after clustered losses.",
                    created_at: "2026-01-01T00:00:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/crew/lessons", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    id: 22,
                    symbol: "BTC-USD",
                    strategy_name: "buy_hold",
                    outcome: "take_profit",
                    return_pct: 6.42,
                    lesson: "Preserve target discipline after profitable exits.",
                    created_at: "2026-01-01T02:00:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/paper/accounts", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([{ id: 5, name: "AI Team Bankroll", cash_balance: 7200, equity: 10300 }]),
        });
    });

    await page.route("**/api/crew/audit", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                { id: 1, event_type: "entry_trigger_executed", recommendation_id: 1, payload: {}, created_at: "2026-01-01T01:00:00Z" },
                { id: 2, event_type: "entry_trigger_blocked", recommendation_id: 2, payload: {}, created_at: "2026-01-01T01:05:00Z" },
            ]),
        });
    });

    await page.route("**/api/crew/activity**", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
                {
                    id: 100,
                    run_id: 7,
                    recommendation_id: 1,
                    thesis_id: 1,
                    snapshot_id: 1,
                    role: "Trigger Monitor",
                    exchange: "kraken",
                    symbol: "BTC-USD",
                    event_type: "trigger_waiting",
                    status: "waiting",
                    public_summary: "BTC-USD position is open; waiting for take-profit or stop-loss.",
                    rationale: null,
                    blocker_reason: "Exit target has not crossed yet.",
                    evidence: { latest_price: 74500, take_profit_target: 76000 },
                    validation_error: null,
                    created_at: "2026-01-01T01:05:00Z",
                },
            ]),
        });
    });

    await page.route("**/api/crew/no-trade-diagnostics", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                active_thesis_count: 1,
                latest_run: null,
                latest_model_failure: {
                    model: "test-model",
                    role: "Thesis Strategist",
                    status: "timeout",
                    timeout_seconds: 60,
                    error_message: "Read timed out.",
                    validation_error: null,
                    created_at: "2026-01-01T01:00:00Z",
                },
                blockers: ["Thesis Strategist model test-model timed out after 60 seconds."],
                recommended_action: "Select a faster local thesis/trade model, then run a dry-run.",
            }),
        });
    });

    await page.route("**/api/crew/autonomy", async (route) => {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(summary.settings) });
    });

    await page.route("**/api/crew/autonomy/start", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ status: "started", bot_state: "running", primary_exchange: "kraken", research_task_id: "task-1" }),
        });
    });

    await page.route("**/api/crew/autonomy/pause", async (route) => {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(summary.settings) });
    });

    await page.route("**/api/backfill/universe?exchange=kraken", async (route) => {
        await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ task_id: "backfill-1" }) });
    });

    await page.route("**/api/crew/research/dry-run", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ ok: true, status: "ok", model: "test-model", exchange: "kraken", symbol: "BTC-USD" }),
        });
    });

    await page.goto("/crew");

    await expect(page.getByRole("heading", { name: /ai trading team/i })).toBeVisible();
    await expect(page.getByText("Primary source and paper venue: KRAKEN")).toBeVisible();
    await expect(page.getByRole("button", { name: /start bot/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /pause bot/i })).toBeVisible();
    await expect(page.getByText("Available bankroll")).toBeVisible();
    await expect(page.getByText("$7,200")).toBeVisible();
    await expect(page.getByText("BTC-USD").first()).toBeVisible();
    await expect(page.getByText("Mocked active thesis with target conditions.")).toBeVisible();
    await expect(page.getByText("Owned Assets")).toBeVisible();
    await expect(page.getByText("Bought And Sold")).toBeVisible();
    await expect(page.getByText("Decision Log")).toBeVisible();
    await expect(page.getByText("Why No Trade Yet?")).toBeVisible();
    await expect(page.getByText("Thesis Strategist model test-model timed out after 60 seconds.")).toBeVisible();
    await expect(page.getByRole("button", { name: /use fast paper-trading defaults/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /run thesis dry-run/i })).toBeVisible();
    await expect(page.getByText("BTC-USD position is open; waiting for take-profit or stop-loss.")).toBeVisible();
    await expect(page.getByText("Preserve target discipline after profitable exits.")).toBeVisible();
    await expect(page.getByText("Reset #2")).toBeVisible();
});
