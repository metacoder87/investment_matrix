
from app.connectors.sentiment import FearAndGreedConnector
from app.connectors.fundamental import CoinGeckoConnector

def test_connectors():
    print("Testing Sentiment & Fundamental Connectors...")
    
    # 1. Fear & Greed
    print("\n[Fear & Greed]")
    fng = FearAndGreedConnector()
    res = fng.get_latest()
    print(f"F&G: {res}")
    
    if res and "value" in res:
        print("SUCCESS: Fear & Greed fetched.")
    else:
        print("WARNING: Fear & Greed failed.")

    # 2. Fundamentals (CoinGecko)
    print("\n[Fundamentals - CoinGecko]")
    cg = CoinGeckoConnector()
    # Test with Bitcoin
    fund = cg.get_coin_fundamentals("bitcoin")
    
    if fund:
        print(f"Data for {fund.get('name')}:")
        print(f"  Market Cap: ${fund.get('market_cap'):,}")
        print(f"  FDV: ${fund.get('fully_diluted_valuation'):,}")
        print(f"  Circulating Supply: {fund.get('circulating_supply'):,}")
        print("SUCCESS: Fundamentals fetched.")
    else:
        print("WARNING: CoinGecko fundamentals failed (rate limit or connection?).")

if __name__ == "__main__":
    test_connectors()
