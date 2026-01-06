import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import create_app
from app.database import get_db, Base
from app.config import settings

# Setup Test DB
# Connect to REAL Postgres or SQLite for integration?
# Using SQLite for speed and isolation usually, but we have Postgres models.
# The `DATABASE_URL` in settings might be the real one.
# For safety, let's use a standard TestClient with the app's current DB connection
# assuming it's a dev environment as per user instructions.
# OR, better: mock the session. But "End-to-End" implies real DB interactions.

app = create_app()
client = TestClient(app)

def test_portfolio_lifecycle():
    # 1. Create Portfolio
    # Use random name to avoid collision
    pf_name = f"TestFund_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/portfolio/", json={"name": pf_name})
    assert res.status_code == 200, res.text
    data = res.json()
    pf_id = data["id"]
    assert data["name"] == pf_name
    assert data["total_value"] == 0.0

    # 2. Buy BTC (1.0 @ 50000)
    res = client.post(f"/api/portfolio/{pf_id}/orders", json={
        "symbol": "BTC-USD",
        "exchange": "coinbase",
        "side": "buy",
        "price": 50000.0,
        "amount": 1.0
    })
    assert res.status_code == 200

    # 3. Buy BTC (1.0 @ 60000) -> Avg Entry should be 55000
    res = client.post(f"/api/portfolio/{pf_id}/orders", json={
        "symbol": "BTC-USD",
        "exchange": "coinbase",
        "side": "buy",
        "price": 60000.0,
        "amount": 1.0
    })
    assert res.status_code == 200

    # 4. Check Holdings
    res = client.get(f"/api/portfolio/{pf_id}")
    assert res.status_code == 200
    portfolio = res.json()
    
    holdings = portfolio["holdings"]
    assert len(holdings) == 1
    btc = holdings[0]
    assert btc["symbol"] == "BTC-USD"
    assert btc["quantity"] == 2.0
    assert btc["avg_entry_price"] == 55000.0

    # 5. Sell Partial (0.5 BTC)
    res = client.post(f"/api/portfolio/{pf_id}/orders", json={
        "symbol": "BTC-USD",
        "exchange": "coinbase",
        "side": "sell",
        "price": 70000.0,
        "amount": 0.5
    })
    assert res.status_code == 200

    # 6. Check Holdings Again
    res = client.get(f"/api/portfolio/{pf_id}")
    portfolio = res.json()
    btc = portfolio["holdings"][0]
    assert btc["quantity"] == 1.5
    # Avg entry price should NOT change on sell
    assert btc["avg_entry_price"] == 55000.0

    print(f"\nVerified Portfolio {pf_id}: {pf_name} successfully.")
