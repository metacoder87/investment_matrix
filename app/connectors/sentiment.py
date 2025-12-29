import requests
from app.config import settings
from datetime import datetime, timedelta

class StockgeistConnector:
    def __init__(self):
        self.api_key = settings.STOCKGEIST_API_KEY
        self.base_url = "https://api.stockgeist.ai/v2"

    def get_crypto_sentiment(self, symbol: str):
        """
        Fetches sentiment for a given cryptocurrency symbol.
        """
        url = f"{self.base_url}/crypto/sentiment"
        params = {
            "symbol": symbol,
            "api_key": self.api_key,
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching sentiment from Stockgeist: {e}")
            return None

class SantimentConnector:
    def __init__(self):
        self._san = None
        if not settings.SANTIMENT_API_KEY:
            return
        try:
            import san  # type: ignore
        except ImportError:
            return
        san.ApiConfig.api_key = settings.SANTIMENT_API_KEY
        self._san = san

    def get_sentiment(self, slug: str):
        """
        Fetches sentiment for a given slug.
        """
        if self._san is None:
            return {"status": "disabled", "reason": "Santiment client not configured"}
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)
        try:
            sentiment_data = self._san.get(
                "sentiment_positive_total",
                slug=slug,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                interval="1d"
            )
            return sentiment_data.to_json()
        except Exception as e:
            print(f"An error occurred while fetching sentiment from Santiment: {e}")
            return None

class LunarCrushConnector:
    def __init__(self):
        self.api_key = settings.LUNARCRUSH_API_KEY
        self.base_url = "https://lunarcrush.com/api4"

    def get_sentiment(self, symbol: str):
        """
        Fetches sentiment for a given cryptocurrency symbol.
        """
        url = f"{self.base_url}/coins/{symbol}/sentiment"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching sentiment from LunarCrush: {e}")
            return None

class CryptoCompareConnector:
    def __init__(self):
        self.api_key = settings.CRYPTOCOMPARE_API_KEY
        self.base_url = "https://min-api.cryptocompare.com"

    def get_sentiment(self, coin_id: str):
        """
        Fetches sentiment for a given coin ID.
        """
        url = f"{self.base_url}/data/social/latest"
        params = {
            "coinId": coin_id,
            "api_key": self.api_key,
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching sentiment from CryptoCompare: {e}")
            return None

class FearAndGreedConnector:
    def __init__(self):
        self.url = "https://api.alternative.me/fng/"

    def get_latest(self):
        """
        Fetches the latest Crypto Fear & Greed Index.
        Returns dict with value (0-100) and classification (e.g. 'Extreme Fear').
        """
        try:
            response = requests.get(self.url)
            response.raise_for_status()
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                item = data["data"][0]
                return {
                    "value": int(item.get("value", 50)),
                    "value_classification": item.get("value_classification", "Neutral"),
                    "timestamp": int(item.get("timestamp", 0)),
                    "time_until_update": int(item.get("time_until_update", 0))
                }
            return None
        except Exception as e:
            print(f"Error fetching Fear & Greed index: {e}")
            return None

class Sentiment:
    def __init__(self):
        self.stockgeist_connector = StockgeistConnector()
        self.santiment_connector = SantimentConnector()
        self.lunarcrush_connector = LunarCrushConnector()
        self.cryptocompare_connector = CryptoCompareConnector()
        self.fng_connector = FearAndGreedConnector()

    def get_sentiment(self, query: str):
        # fng is global, not per-symbol usually, but we include it contextually
        fng = self.fng_connector.get_latest()
        
        stockgeist_sentiment = self.stockgeist_connector.get_crypto_sentiment(symbol=query)
        santiment_sentiment = self.santiment_connector.get_sentiment(slug=query)
        lunarcrush_sentiment = self.lunarcrush_connector.get_sentiment(symbol=query)
        cryptocompare_sentiment = self.cryptocompare_connector.get_sentiment(coin_id=query)
        
        return {
            "fear_and_greed": fng,
            "stockgeist": stockgeist_sentiment,
            "santiment": santiment_sentiment,
            "lunarcrush": lunarcrush_sentiment,
            "cryptocompare": cryptocompare_sentiment,
        }
