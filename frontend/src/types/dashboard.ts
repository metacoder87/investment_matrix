export interface PortfolioSummary {
    source?: "ai" | "user";
    portfolio_count?: number;
    available_bankroll: number;
    cash_balance: number;
    invested_value: number;
    total_cost?: number;
    total_equity: number;
    long_exposure: number;
    short_exposure: number;
    realized_pnl: number;
    unrealized_pnl: number;
    all_time_pnl: number;
    current_cycle_pnl: number;
    drawdown_pct: number;
    exposure_pct: number;
    open_positions: number;
    sleeve_win_rates: Record<"long" | "short", number>;
    closed_win_rate?: number | null;
    closed_trade_count?: number;
    closed_wins?: number;
    closed_losses?: number;
    positions?: Position[];
    recent_orders?: DashboardOrder[];
}

export interface EquityPoint {
    timestamp: string | null;
    cash_balance: number;
    invested_value: number;
    equity: number;
    drawdown_pct: number;
}

export interface Position {
    symbol: string;
    exchange: string;
    side: string;
    quantity: number;
    last_price: number;
    avg_entry_price: number;
    market_value: number;
    unrealized_pnl: number;
    return_pct: number;
}

export interface ThesisLite {
    id: number;
    symbol: string;
    exchange: string;
    side?: string | null;
    confidence: number;
    status: string;
    strategy_name: string;
}

export interface TraceEventLite {
    id: number;
    role: string;
    status: string;
    symbol: string | null;
    exchange: string | null;
    public_summary: string;
    created_at: string | null;
}

export interface DashboardOrder {
    id: number;
    portfolio_id?: number;
    portfolio_name?: string;
    symbol: string;
    exchange: string;
    side: string;
    status: string;
    price: number;
    amount?: number;
    quantity?: number;
    realized_pnl?: number | null;
    timestamp?: string | null;
}
