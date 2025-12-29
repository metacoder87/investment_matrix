import sys
import os

sys.path.append(os.getcwd())

try:
    from app.signals.engine import SignalEngine
    from app.connectors.sentiment import Sentiment
    from app.connectors.coinmarketcap import CoinMarketCapConnector
    print("✅ Success: Imports working correctly.")
except ImportError as e:
    print(f"❌ Error: Import failed - {e}")
except Exception as e:
    print(f"❌ Error: {e}")
