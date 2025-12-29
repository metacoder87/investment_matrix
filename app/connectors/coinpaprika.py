import requests
from app.config import settings


class CoinPaprikaConnector:
    """
    Connector for CoinPaprika API.
    
    CoinPaprika offers free tier access for coin data. Note that some endpoints
    like events/news may have limited availability.
    """

    def __init__(self):
        self.api_key = settings.COINPAPRIKA_API_KEY
        self.base_url = "https://api.coinpaprika.com/v1"

    def get_news(self, coin_id: str):
        """
        Fetches events/updates for a given coin ID.
        
        CoinPaprika uses 'events' endpoint for news-like data.
        The API is free but rate-limited.
        """
        # CoinPaprika uses /coins/{coin_id}/events for news-like updates
        url = f"{self.base_url}/coins/{coin_id}/events"
        headers = {}
        if self.api_key:
            headers["Authorization"] = self.api_key
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 404:
                return {"status": "not_found", "reason": f"Coin '{coin_id}' not found", "events": []}
            if response.status_code == 429:
                return {"status": "rate_limited", "reason": "Too many requests", "events": []}
            response.raise_for_status()
            events = response.json()
            # Normalize to consistent format
            return {"status": "ok", "events": events if isinstance(events, list) else []}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "reason": str(e), "events": []}

