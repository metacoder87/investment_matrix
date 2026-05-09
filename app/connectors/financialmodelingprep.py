import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class FinancialModelingPrepConnector:
    def __init__(self):
        self.api_key = settings.FINANCIALMODELINGPREP_API_KEY
        self.base_url = "https://financialmodelingprep.com/api/v3"

    def get_crypto_news(self, symbol: str):
        """
        Fetches news for a given cryptocurrency symbol.
        """
        url = f"{self.base_url}/crypto/news"
        params = {
            "symbol": symbol,
            "apikey": self.api_key,
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning("FinancialModelingPrep fetch failed: %s", e)
            return None
