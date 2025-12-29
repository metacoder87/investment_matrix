import sys
import os

# Add the project root to the python path
sys.path.append(os.getcwd())

from app.connectors.news_api import NewsConnector
from app.connectors.coinmarketcap import CoinMarketCapConnector

def test_news_api():
    print("\n--- Testing NewsAPI ---")
    connector = NewsConnector()
    result = connector.get_crypto_news(query="bitcoin")
    
    if "status" in result and result["status"] == "error":
        print(f"❌ Error: {result['reason']}")
    elif "status" in result and result["status"] == "disabled":
        print(f"⚠️ Disabled: {result['reason']}")
    else:
        articles = result.get("articles", [])
        print(f"✅ Success: Fetched {len(articles)} articles.")
        for i, article in enumerate(articles[:3]):
            print(f"   {i+1}. {article.get('title')}")

def test_cmc_fundamentals():
    print("\n--- Testing CoinMarketCap Fundamentals ---")
    connector = CoinMarketCapConnector()
    # Note: Using 'BTC' as symbol. The connector implementation usually expects symbol (e.g. BTC) or slug (e.g. bitcoin) depending on endpoint.
    # quotes/latest takes symbol or slug or id.
    result = connector.get_fundamentals(symbol="BTC")
    
    if not result:
        print("❌ Error: Returned None.")
    elif "status" in result and result["status"] == "error":
        print(f"❌ Error: {result['reason']}")
    elif "status" in result and result["status"] == "disabled":
        print(f"⚠️ Disabled: {result['reason']}")
    else:
        print("✅ Success: Fetched fundamentals.")
        print(f"   Name: {result.get('name')}")
        print(f"   Symbol: {result.get('symbol')}")
        print(f"   Market Cap: ${result.get('market_cap'):,.2f}")
        print(f"   Total Supply: {result.get('total_supply'):,.0f}")

if __name__ == "__main__":
    test_news_api()
    test_cmc_fundamentals()
