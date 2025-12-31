import sys
import os

sys.path.append(os.getcwd())

try:
    from app.signals.engine import SignalEngine  # noqa: F401
    from app.connectors.sentiment import Sentiment  # noqa: F401
    from app.connectors.coinmarketcap import CoinMarketCapConnector  # noqa: F401
    print("✅ Success: Imports working correctly.")
except ImportError as e:
    print(f"❌ Error: Import failed - {e}")
except Exception as e:
    print(f"❌ Error: {e}")
