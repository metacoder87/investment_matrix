from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from starlette.concurrency import run_in_threadpool

from database import get_db
from app.models.portfolio import Portfolio, Order, Holding, OrderSide, OrderStatus
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


# --- Endpoints ---

@router.post("/", response_model=PortfolioSummary)
def create_portfolio(pf: PortfolioCreate, db: Session = Depends(get_db)):
    exist = db.query(Portfolio).filter(Portfolio.name == pf.name).first()
    if exist:
        raise HTTPException(400, "Portfolio name already exists")
    
    new_pf = Portfolio(name=pf.name)
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

@router.get("/", response_model=List[dict])
def list_portfolios(db: Session = Depends(get_db)):
    # Simple list (for dropdowns)
    pfs = db.query(Portfolio).all()
    return [{"id": p.id, "name": p.name} for p in pfs]

@router.get("/{id}", response_model=PortfolioSummary)
async def get_portfolio(id: int, db: Session = Depends(get_db)):
    # Run blocking DB query in threadpool
    def _get_pf():
        return db.query(Portfolio).options(joinedload(Portfolio.holdings)).filter(Portfolio.id == id).first()
    
    pf = await run_in_threadpool(_get_pf)
    
    if not pf:
        raise HTTPException(404, "Portfolio not found")

    holdings_resp = []
    total_value = 0.0
    total_cost = 0.0

    if pf.holdings:
        # Batch fetch prices
        symbols = [h.symbol for h in pf.holdings]
        keys = [f"latest:{sym}" for sym in symbols]
        
        # Determine exchange-specific keys if possible (naive batching here)
        # Ideally we'd use h.exchange, but let's stick to simple efficient latest:{symbol}
        # or specific if recorded. For simplicity, just use latest:{symbol} as primary cache.
        
        raw_values = await redis_client.mget(keys)
        price_map = {}
        for sym, raw in zip(symbols, raw_values):
            if raw:
                try:
                    data = json.loads(raw)
                    price_map[sym] = float(data.get("price", 0.0))
                except:
                    price_map[sym] = 0.0
            else:
                price_map[sym] = 0.0

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
def create_order(id: int, order: OrderCreate, db: Session = Depends(get_db)):
    pf = db.query(Portfolio).filter(Portfolio.id == id).first()
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
        Holding.symbol == new_order.symbol
    ).first()
    
    if not holding:
        if order.side == OrderSide.SELL:
             raise HTTPException(400, "Cannot sell asset you do not own")
        holding = Holding(
            portfolio_id=id,
            symbol=new_order.symbol,
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
