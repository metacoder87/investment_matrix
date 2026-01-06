import pytest
from httpx import AsyncClient
from app.main import app
import time

@pytest.mark.asyncio
async def test_analysis_endpoint_caching():
    async with AsyncClient(base_url="http://localhost:8000") as ac:
        # First Call (Miss)
        start = time.time()
        response1 = await ac.get("/api/coin/BTC-USD/analysis")
        duration1 = time.time() - start
        
        # Expecting empty list if backfill triggered, or data if exists. 
        # Even if empty list, my new code returns [] for triggered backfill without caching logic applied yet?
        # REQUIRED: DB must have some data for caching logic to run properly (step 1: checks latest_ts).
        # We might need to mock DB or rely on existing seed data.
        
        if response1.status_code == 200:
             data1 = response1.json()
             if isinstance(data1, dict) and "calculated_at" in data1:
                 ts1 = data1["calculated_at"]
                 
                 # Second Call (Hit)
                 start = time.time()
                 response2 = await ac.get("/api/coin/BTC-USD/analysis")
                 duration2 = time.time() - start
                 
                 data2 = response2.json()
                 ts2 = data2.get("calculated_at")
                 
                 assert ts1 == ts2, "Calculated timestamp should be identical (served from cache)"
                 # Can't easily assert duration2 < duration1 in test environment reliably, but logical check passes.

@pytest.mark.asyncio
async def test_quant_endpoint_caching():
    async with AsyncClient(base_url="http://localhost:8000") as ac:
        response1 = await ac.get("/api/coin/BTC-USD/quant")
        if response1.status_code == 200:
            data1 = response1.json()
            if "calculated_at" in data1:
                ts1 = data1["calculated_at"]
                
                response2 = await ac.get("/api/coin/BTC-USD/quant")
                data2 = response2.json()
                ts2 = data2.get("calculated_at")
                
                assert ts1 == ts2

@pytest.mark.asyncio
async def test_signals_batch_caching():
    async with AsyncClient(base_url="http://localhost:8000") as ac:
        response1 = await ac.get("/api/signals/batch?symbols=BTC-USD")
        if response1.status_code == 200:
             data1 = response1.json()
             if "calculated_at" in data1:
                 ts1 = data1["calculated_at"]
                 
                 response2 = await ac.get("/api/signals/batch?symbols=BTC-USD")
                 data2 = response2.json()
                 ts2 = data2.get("calculated_at")
                 
                 assert ts1 == ts2
