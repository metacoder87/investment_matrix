import sys
import os
import asyncio

sys.path.append(os.getcwd())

from app.connectors.news_api import NewsConnector
from app.connectors.coinpaprika import CoinPaprikaConnector
from app.connectors.financialmodelingprep import FinancialModelingPrepConnector
from app.connectors.newsdata_io import NewsDataIoConnector

async def verify_sources():
    print("--- Verifying News Sources ---")
    
    # 1. NewsAPI
    print("\n1. Testing NewsAPI...")
    try:
        n = NewsConnector()
        res = n.get_crypto_news(query="bitcoin", page_size=2)
        if res.get("status") == "ok":
            print(f"✅ NewsAPI: Found {res.get('totalResults')} articles")
        elif res.get("status") == "disabled":
            print(f"⚠️ NewsAPI: Disabled ({res.get('reason')})")
        else:
            print(f"❌ NewsAPI: Error - {res.get('reason')}")
    except Exception as e:
        print(f"❌ NewsAPI: Exception - {e}")

    # 2. Coinpaprika
    print("\n2. Testing CoinPaprika (Events)...")
    try:
        cp = CoinPaprikaConnector()
        # Paprika needs ID. Try "btc-bitcoin"
        res = cp.get_news("btc-bitcoin")
        status = res.get("status")
        if status == "ok":
             events = res.get("events", [])
             print(f"✅ CoinPaprika: Found {len(events)} events")
             if events: print(f"   Sample: {events[0].get('name')} - {events[0].get('date')}")
        elif status == "not_found":
             print("⚠️ CoinPaprika: Coin ID not found (expected for some inputs)")
        else:
             print(f"❌ CoinPaprika: {status} - {res.get('reason')}")
    except Exception as e:
        print(f"❌ CoinPaprika: Exception - {e}")

    # 3. Financial Modeling Prep
    print("\n3. Testing Financial Modeling Prep...")
    try:
        fmp = FinancialModelingPrepConnector()
        res = fmp.get_crypto_news("BTC")
        if isinstance(res, list):
            print(f"✅ FMP: Found {len(res)} articles")
            if res: print(f"   Sample: {res[0].get('title')}")
        else:
            print(f"❌ FMP: Unexpected response - {res}")
    except Exception as e:
         print(f"❌ FMP: Exception - {e}")

    # 4. NewsData.io
    print("\n4. Testing NewsData.io...")
    try:
        nd = NewsDataIoConnector()
        res = nd.get_crypto_news("bitcoin")
        if res and "results" in res:
            print(f"✅ NewsData.io: Found {len(res['results'])} results")
        elif res and "status" in res and res["status"] == "error":
             print(f"❌ NewsData.io: Error - {res.get('results', {}).get('message') or res}")
        else:
             print(f"❌ NewsData.io: Unknown response - {res}")
    except Exception as e:
         print(f"❌ NewsData.io: Exception - {e}")

if __name__ == "__main__":
    asyncio.run(verify_sources())
