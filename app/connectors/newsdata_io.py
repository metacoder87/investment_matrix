import requests
from app.config import settings

class NewsDataIoConnector:
    def __init__(self):
        self.api_key = settings.NEWSDATAIO_API_KEY
        self.base_url = "https://newsdata.io/api/1"

    def get_crypto_news(self, query: str):
        """
        Fetches news for a given cryptocurrency query.
        """
        url = f"{self.base_url}/news"
        params = {
            "q": query,
            "crypto": 1,
            "apikey": self.api_key,
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching news from NewsData.io: {e}")
            return None
