from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from database import get_db
from app.models.portfolio import Portfolio, Order, Holding, OrderSide, OrderStatus
from app.models.user import User
from app.routers.auth import get_current_user
from app.redis_client import redis_client
import json

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


# --- Pydantic Schemas ---
class PortfolioCreate(BaseModel):
    name: str

class OrderCreate(BaseModel):
    symbol: str
    exchange: str
    side: OrderSide
    price: float
    amount: float

class HoldingResponse(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: Optional[float] = None
    value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    pnl_percent: Optional[float] = None

class PortfolioSummary(BaseModel):
    id: int
    name: str
    total_value: float
    total_cost: float
    unrealized_pnl: float
    holdings: List[HoldingResponse]

class DashboardPositionResponse(BaseModel):
    symbol: str
    exchange: str
    side: str
    quantity: float
    avg_entry_price: float
    last_price: float
    market_value: float
    unrealized_pnl: float
    return_pct: float

class DashboardOrderResponse(BaseModel):
    id: int
    portfolio_id: int
    portfolio_name: str
    symbol: str
    exchange: str
    side: str
    status: str
    price: float
    amount: float
    realized_pnl: Optional[float] = None
    timestamp: Optional[str] = None

class PortfolioDashboardResponse(BaseModel):
    source: str
    portfolio_count: int
    available_bankroll: float
    cash_balance: float
    invested_value: float
    total_cost: float
    total_equity: float
    long_exposure: float
    short_exposure: float
    realized_pnl: float
    unrealized_pnl: float
    all_time_pnl: float
    current_cycle_pnl: float
    drawdown_pct: float
    exposure_pct: float
    open_positions: int
    sleeve_win_rates: dict[str, float]
    closed_win_rate: Optional[float]
    closed_trade_count: int
    closed_wins: int
    closed_losses: int
    positions: List[DashboardPositionResponse]
    recent_orders: List[DashboardOrderResponse]


# --- Endpoints ---

@router.post("", response_model=PortfolioSummary, include_in_schema=False)
@router.post("/", response_model=PortfolioSummary)
def create_portfolio(
    pf: PortfolioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exist = (
        db.query(Portfolio)
        .filter(Portfolio.user_id == current_user.id, Portfolio.name == pf.name)
        .first()
    )
    if exist:
        raise HTTPException(400, "Portfolio name already exists")
    
    new_pf = Portfolio(name=pf.name, user_id=current_user.id)
    db.add(new_pf)
    db.commit()
    db.refresh(new_pf)
    return {
        "id": new_pf.id,
        "name": new_pf.name,
        "total_value": 0.0,
        "total_cost": 0.0,
        "unrealized_pnl": 0.0,
        "holdings": []
    }

@router.get("", response_model=List[dict], include_in_schema=False)
@router.get("/", response_model=List[dict])
def list_portfolios(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Simple list (for dropdowns)
    pfs = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    return [{"id": p.id, "name": p.name} for p in pfs]

@router.get("/dashboard", response_model=PortfolioDashboardResponse)
async def get_portfolio_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    portfolios = (
        db.query(Portfolio)
        .options(joinedload(Portfolio.holdings))
        .filter(Portfolio.user_id == current_user.id)
        .order_by(Portfolio.name.asc())
        .all()
    )
    portfolio_ids = [portfolio.id for portfolio in portfolios]
    holdings = [holding for portfolio in portfolios for holding in portfolio.holdings]
    price_map = await _latest_price_map([holding.symbol for holding in holdings])

    positions = []
    total_value = 0.0
    total_cost = 0.0
    for holding in holdings:
        current_price = price_map.get(holding.symbol, 0.0) or float(holding.avg_entry_price or 0.0)
        quantity = float(holding.quantity or 0.0)
        avg_entry = float(holding.avg_entry_price or 0.0)
        market_value = quantity * current_price
        cost_basis = quantity * avg_entry
        unrealized = market_value - cost_basis
        return_pct = ((current_price / avg_entry) - 1.0) * 100 if avg_entry > 0 else 0.0

        total_value += market_value
        total_cost += cost_basis
        positions.append(
            DashboardPositionResponse(
                symbol=holding.symbol,
                exchange=holding.exchange,
                side="long",
                quantity=quantity,
                avg_entry_price=avg_entry,
                last_price=current_price,
                market_value=market_value,
                unrealized_pnl=unrealized,
                return_pct=return_pct,
            )
        )

    orders = (
        db.query(Order, Portfolio.name)
        .join(Portfolio, Portfolio.id == Order.portfolio_id)
        .filter(Portfolio.user_id == current_user.id, Order.status == OrderStatus.FILLED)
        .order_by(Order.timestamp.asc(), Order.id.asc())
        .all()
        if portfolio_ids
        else []
    )
    realized_pnl, closed_wins, closed_losses, realized_by_order = _realized_trade_stats([row[0] for row in orders])
    closed_trade_count = closed_wins + closed_losses
    closed_win_rate = (closed_wins / closed_trade_count) if closed_trade_count else None

    recent_orders = [
        DashboardOrderResponse(
            id=order.id,
            portfolio_id=order.portfolio_id,
            portfolio_name=portfolio_name,
            symbol=order.symbol,
            exchange=order.exchange,
            side=order.side.value,
            status=order.status.value,
            price=float(order.price or 0.0),
            amount=float(order.amount or 0.0),
            realized_pnl=realized_by_order.get(order.id),
            timestamp=order.timestamp.isoformat() if order.timestamp else None,
        )
        for order, portfolio_name in sorted(orders, key=lambda row: (row[0].timestamp, row[0].id), reverse=True)[:10]
    ]

    unrealized_pnl = total_value - total_cost
    all_time_pnl = realized_pnl + unrealized_pnl
    return PortfolioDashboardResponse(
        source="user",
        portfolio_count=len(portfolios),
        available_bankroll=0.0,
        cash_balance=0.0,
        invested_value=total_cost,
        total_cost=total_cost,
        total_equity=total_value,
        long_exposure=total_value,
        short_exposure=0.0,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        all_time_pnl=all_time_pnl,
        current_cycle_pnl=all_time_pnl,
        drawdown_pct=0.0,
        exposure_pct=100.0 if total_value > 0 else 0.0,
        open_positions=len(positions),
        sleeve_win_rates={"long": 0.0, "short": 0.0},
        closed_win_rate=closed_win_rate,
        closed_trade_count=closed_trade_count,
        closed_wins=closed_wins,
        closed_losses=closed_losses,
        positions=positions,
        recent_orders=recent_orders,
    )

@router.get("/{id}", response_model=PortfolioSummary)
async def get_portfolio(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pf = (
        db.query(Portfolio)
        .options(joinedload(Portfolio.holdings))
        .filter(Portfolio.id == id, Portfolio.user_id == current_user.id)
        .first()
    )
    
    if not pf:
        raise HTTPException(404, "Portfolio not found")

    holdings_resp = []
    total_value = 0.0
    total_cost = 0.0

    if pf.holdings:
        price_map = await _latest_price_map([h.symbol for h in pf.holdings])

        for h in pf.holdings:
            current_price = price_map.get(h.symbol, 0.0)
            
            # Fallback
            if current_price == 0:
                current_price = h.avg_entry_price

            val = h.quantity * current_price
            cost = h.quantity * h.avg_entry_price
            
            pnl = val - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
            
            total_value += val
            total_cost += cost
            
            holdings_resp.append({
                "symbol": h.symbol,
                "quantity": h.quantity,
                "avg_entry_price": h.avg_entry_price,
                "current_price": current_price,
                "value": val,
                "unrealized_pnl": pnl,
                "pnl_percent": pnl_pct
            })

    return {
        "id": pf.id,
        "name": pf.name,
        "total_value": total_value,
        "total_cost": total_cost,
        "unrealized_pnl": total_value - total_cost,
        "holdings": holdings_resp
    }

@router.post("/{id}/orders")
def create_order(
    id: int,
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pf = (
        db.query(Portfolio)
        .filter(Portfolio.id == id, Portfolio.user_id == current_user.id)
        .first()
    )
    if not pf:
        raise HTTPException(404, "Portfolio not found")

    # Record Order
    new_order = Order(
        portfolio_id=id,
        symbol=order.symbol.upper(),
        exchange=order.exchange.lower(),
        side=order.side,
        price=order.price,
        amount=order.amount,
        status=OrderStatus.FILLED
    )
    db.add(new_order)
    
    # Update Holding
    holding = db.query(Holding).filter(
        Holding.portfolio_id == id, 
        Holding.symbol == new_order.symbol,
        Holding.exchange == new_order.exchange
    ).first()
    
    if not holding:
        if order.side == OrderSide.SELL:
             raise HTTPException(400, "Cannot sell asset you do not own")
        holding = Holding(
            portfolio_id=id,
            symbol=new_order.symbol,
            exchange=new_order.exchange,
            quantity=0.0,
            avg_entry_price=0.0
        )
        db.add(holding)
    
    if order.side == OrderSide.BUY:
        # Weighted Average Entry Price
        total_cost = (holding.quantity * holding.avg_entry_price) + (order.amount * order.price)
        total_qty = holding.quantity + order.amount
        holding.avg_entry_price = total_cost / total_qty
        holding.quantity = total_qty
    else:
        # Sell reduces quantity
        if holding.quantity < order.amount:
             raise HTTPException(400, "Insufficient holdings")
        holding.quantity -= order.amount
        if holding.quantity <= 0:
            db.delete(holding)
            
    db.commit()
    return {"status": "created", "order_id": new_order.id}


async def _latest_price_map(symbols: list[str]) -> dict[str, float]:
    keys = [f"latest:{symbol}" for symbol in symbols]
    try:
        raw_values = await redis_client.mget(keys)
    except Exception:
        raw_values = [None] * len(keys)

    price_map: dict[str, float] = {}
    for symbol, raw in zip(symbols, raw_values):
        if raw:
            try:
                data = json.loads(raw)
                price_map[symbol] = float(data.get("price", 0.0))
            except (TypeError, ValueError, json.JSONDecodeError):
                price_map[symbol] = 0.0
        else:
            price_map[symbol] = 0.0
    return price_map


def _realized_trade_stats(orders: list[Order]) -> tuple[float, int, int, dict[int, float]]:
    lots: dict[tuple[int, str, str], dict[str, float]] = {}
    realized_by_order: dict[int, float] = {}
    realized_total = 0.0
    wins = 0
    losses = 0

    for order in sorted(orders, key=lambda item: (item.timestamp, item.id)):
        key = (order.portfolio_id, order.symbol, order.exchange)
        lot = lots.setdefault(key, {"quantity": 0.0, "avg_entry_price": 0.0})
        amount = float(order.amount or 0.0)
        price = float(order.price or 0.0)

        if order.side == OrderSide.BUY:
            new_quantity = lot["quantity"] + amount
            if new_quantity > 0:
                lot["avg_entry_price"] = (
                    (lot["quantity"] * lot["avg_entry_price"]) + (amount * price)
                ) / new_quantity
            lot["quantity"] = new_quantity
            continue

        if order.side == OrderSide.SELL and amount > 0:
            pnl = (price - lot["avg_entry_price"]) * amount
            realized_by_order[order.id] = pnl
            realized_total += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            lot["quantity"] = max(0.0, lot["quantity"] - amount)
            if lot["quantity"] == 0:
                lot["avg_entry_price"] = 0.0

    return realized_total, wins, losses, realized_by_order
