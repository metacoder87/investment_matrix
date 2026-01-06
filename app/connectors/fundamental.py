from pycoingecko import CoinGeckoAPI


class CoinGeckoConnector:
    """
    A connector for fetching cryptocurrency data from the CoinGecko API.

    This class provides methods to access various endpoints of the CoinGecko API,
    allowing the retrieval of coin lists, market data, and other fundamental
    information.
    """

    def __init__(self):
        """
        Initializes the CoinGeckoAPI client.
        """
        pass

    def get_all_coins(self, **kwargs):
        """
        Fetches a list of all cryptocurrencies from CoinGecko.

        Args:
            **kwargs: Additional keyword arguments to pass to the API call,
                      such as 'per_page' and 'page'.

        Returns:
            A list of dictionaries, where each dictionary contains market data
            for a cryptocurrency.
        """
        try:
            client = CoinGeckoAPI()
            # The 'vs_currency' is a required parameter for get_coins_markets
            if 'vs_currency' not in kwargs:
                kwargs['vs_currency'] = 'usd'
            return client.get_coins_markets(**kwargs)
        except Exception as e:
            print(f"An error occurred while fetching all coins from CoinGecko: {e}")
            return []

    _coins_cache = None
    _coins_cache_ts = 0
    CACHE_DURATION = 3600  # 1 hour

    def get_coin_id_by_symbol(self, symbol: str) -> str | None:
        """
        Attempts to resolve a symbol (e.g. 'BTC') to a CoinGecko ID (e.g. 'bitcoin').
        Uses in-memory caching to avoid repeated API calls.
        """
        import time
        
        try:
            # Clean symbol (remove -USD etc)
            clean_sym = symbol.split("-")[0].lower()
            
            # Refresh cache if empty or stale
            now = time.time()
            if not self._coins_cache or (now - self._coins_cache_ts > self.CACHE_DURATION):
                # Fetch top 250 coins which covers 99% of use cases
                self._coins_cache = self.get_all_coins(per_page=250, page=1)
                self._coins_cache_ts = now
                
            for cw in self._coins_cache:
                if cw.get("symbol") == clean_sym:
                    return cw.get("id")
                    
            # Fallback: if not in top 250, maybe fetch specific search?
            # For now, return None to avoid heavy full-list fetch
            return None
        except Exception:
            return None

    def get_coin_details(self, coin_id: str):
        """
        Fetches detailed information for a specific cryptocurrency.

        Args:
            coin_id (str): The unique identifier for the coin on CoinGecko (e.g., 'bitcoin').

        Returns:
            A dictionary containing detailed information about the coin, or None
            if an error occurs.
        """
        try:
            client = CoinGeckoAPI()
            return client.get_coin_by_id(coin_id)
        except Exception as e:
            print(f"An error occurred while fetching details for '{coin_id}' from CoinGecko: {e}")
            return None

    def ping(self) -> bool:
        """
        Checks if the CoinGecko API is reachable.

        Returns:
            True if the API is reachable, False otherwise.
        """
        try:
            client = CoinGeckoAPI()
            return client.ping().get('gecko_says', '') == '(V3) To the Moon!'
        except Exception as e:
            print(f"An error occurred while pinging CoinGecko API: {e}")
            return False

    def get_status_updates(self, coin_id: str = None):
        """
        Fetches status updates from CoinGecko.

        Args:
            coin_id (str, optional): The coin ID to fetch status updates for. 
                                     If None, fetches global status updates.

        Returns:
            A list of status updates, or an empty list if an error occurs.
        """
        try:
            client = CoinGeckoAPI()
            if coin_id:
                return client.get_coin_status_updates_by_id(coin_id)
            else:
                return client.get_status_updates()
        except Exception as e:
            print(f"An error occurred while fetching status updates from CoinGecko: {e}")
            return []

    def get_coin_fundamentals(self, coin_id: str):
        """
        Fetches and extracts key fundamental metrics for a coin.
        Returns dict with market_cap, fdv, supply stats, and ATH/ATL.
        """
        details = self.get_coin_details(coin_id)
        if not details:
            return None
        
        market_data = details.get("market_data", {})
        
        # Extract standardized metrics
        return {
            "name": details.get("name"),
            "symbol": details.get("symbol"),
            "market_cap": market_data.get("market_cap", {}).get("usd"),
            "fully_diluted_valuation": market_data.get("fully_diluted_valuation", {}).get("usd"),
            "total_supply": market_data.get("total_supply"),
            "max_supply": market_data.get("max_supply"),
            "circulating_supply": market_data.get("circulating_supply"),
            "ath": market_data.get("ath", {}).get("usd"),
            "ath_date": market_data.get("ath_date", {}).get("usd"),
            "atl": market_data.get("atl", {}).get("usd"),
            "atl_date": market_data.get("atl_date", {}).get("usd"),
            "genesis_date": details.get("genesis_date")
        }