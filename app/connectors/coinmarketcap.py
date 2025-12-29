import requests
from app.config import settings


class CoinMarketCapConnector:
    """
    Connector for CoinMarketCap API.
    
    Note: The free tier has limited endpoints. News is NOT available on the free plan.
    This connector provides graceful degradation when the API key is missing or
    when requesting unavailable endpoints.
    """

    def __init__(self):
        self.api_key = settings.COINMARKETCAP_API_KEY
        self.base_url = "https://pro-api.coinmarketcap.com"


    def get_fundamentals(self, symbol: str):
        """
        Fetches and extracts key fundamental metrics for a coin using CMC `v1/cryptocurrency/quotes/latest`.
        
        Args:
            symbol: The cryptocurrency symbol (e.g., 'BTC', 'ETH').
        
        Returns:
            dict: A dictionary containing market cap, supply stats, etc.
        """
        if not self.api_key:
            return {"status": "disabled", "reason": "COINMARKETCAP_API_KEY not set"}

        headers = {
            "Accepts": "application/json",
            "X-CMC_PRO_API_KEY": self.api_key,
        }
        url = f"{self.base_url}/v1/cryptocurrency/quotes/latest"
        parameters = {
            "symbol": symbol.upper(),
        }

        try:
            response = requests.get(url, headers=headers, params=parameters, timeout=10)
            if response.status_code == 401:
                return {"status": "error", "reason": "Invalid API key"}
            if response.status_code == 402:
                # Basic tier should include this, but handle payment required just in case
                return {"status": "disabled", "reason": "Plan limits exceeded or endpoint restricted"}
            
            response.raise_for_status()
            data = response.json()
            
            # The response format is { "data": { "BTC": { ... } }, "status": ... }
            sym = symbol.upper()
            if "data" not in data or sym not in data["data"]:
                return None
            
            coin_data = data["data"][sym]
            quote = coin_data.get("quote", {}).get("USD", {})
            
            return {
                "name": coin_data.get("name"),
                "symbol": coin_data.get("symbol"),
                "market_cap": quote.get("market_cap"),
                "fully_diluted_valuation": quote.get("fully_diluted_market_cap"),
                "total_supply": coin_data.get("total_supply"),
                "max_supply": coin_data.get("max_supply"),
                "circulating_supply": coin_data.get("circulating_supply"),
                "ath": None, # Not available in quotes/latest
                "ath_date": None,
                "atl": None,
                "atl_date": None,
                "genesis_date": coin_data.get("date_added") # Approximate
            }

        except requests.exceptions.RequestException as e:
            return {"status": "error", "reason": str(e)}

