from pycoingecko import CoinGeckoAPI


class CoinGeckoConnector:
    """
    A connector for fetching cryptocurrency data from the CoinGecko API.

    This class provides methods to access various endpoints of the CoinGecko API,
    allowing the retrieval of coin lists, market data, and other fundamental
    information.
    """

    def get_all_coins(self, **kwargs):
        """
        Fetches a list of all cryptocurrencies from CoinGecko.
        Falls back to a static list if the API is unreachable (Rate Limited).
        """
        try:
            client = CoinGeckoAPI()
            # The 'vs_currency' is a required parameter for get_coins_markets
            if 'vs_currency' not in kwargs:
                kwargs['vs_currency'] = 'usd'
            return client.get_coins_markets(**kwargs)
        except Exception as e:
            print(f"Warning: CoinGecko API failed ({e}). Using fallback coin list.")
            return self._get_fallback_coins()

    def _get_fallback_coins(self):
        """Returns a static list of top coins for offline/fallback mode."""
        return [
            {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "image": "https://assets.coingecko.com/coins/images/1/large/bitcoin.png", "current_price": 65000, "market_cap": 1200000000000, "market_cap_rank": 1},
            {"id": "ethereum", "symbol": "eth", "name": "Ethereum", "image": "https://assets.coingecko.com/coins/images/279/large/ethereum.png", "current_price": 3500, "market_cap": 400000000000, "market_cap_rank": 2},
            {"id": "tether", "symbol": "usdt", "name": "Tether", "image": "https://assets.coingecko.com/coins/images/325/large/Tether.png", "current_price": 1.0, "market_cap": 100000000000, "market_cap_rank": 3},
            {"id": "binancecoin", "symbol": "bnb", "name": "BNB", "image": "https://assets.coingecko.com/coins/images/825/large/bnb-icon2_2x.png", "current_price": 600, "market_cap": 90000000000, "market_cap_rank": 4},
            {"id": "solana", "symbol": "sol", "name": "Solana", "image": "https://assets.coingecko.com/coins/images/4128/large/solana.png", "current_price": 150, "market_cap": 70000000000, "market_cap_rank": 5},
            {"id": "ripple", "symbol": "xrp", "name": "XRP", "image": "https://assets.coingecko.com/coins/images/44/large/xrp-symbol-white-128.png", "current_price": 0.60, "market_cap": 30000000000, "market_cap_rank": 6},
            {"id": "usd-coin", "symbol": "usdc", "name": "USDC", "image": "https://assets.coingecko.com/coins/images/6319/large/USD_Coin_icon.png", "current_price": 1.0, "market_cap": 30000000000, "market_cap_rank": 7},
            {"id": "staked-ether", "symbol": "steth", "name": "Lido Staked Ether", "image": "https://assets.coingecko.com/coins/images/13442/large/steth_logo.png", "current_price": 3500, "market_cap": 30000000000, "market_cap_rank": 8},
            {"id": "cardano", "symbol": "ada", "name": "Cardano", "image": "https://assets.coingecko.com/coins/images/975/large/cardano.png", "current_price": 0.45, "market_cap": 16000000000, "market_cap_rank": 9},
            {"id": "avalanche-2", "symbol": "avax", "name": "Avalanche", "image": "https://assets.coingecko.com/coins/images/12559/large/Avalanche_Circle_RedWhite_Trans.png", "current_price": 35.0, "market_cap": 13000000000, "market_cap_rank": 10},
            {"id": "dogecoin", "symbol": "doge", "name": "Dogecoin", "image": "https://assets.coingecko.com/coins/images/5/large/dogecoin.png", "current_price": 0.15, "market_cap": 20000000000, "market_cap_rank": 11},
            {"id": "shiba-inu", "symbol": "shib", "name": "Shiba Inu", "image": "https://assets.coingecko.com/coins/images/11939/large/shiba.png", "current_price": 0.000025, "market_cap": 15000000000, "market_cap_rank": 12},
            {"id": "polkadot", "symbol": "dot", "name": "Polkadot", "image": "https://assets.coingecko.com/coins/images/12171/large/polkadot.png", "current_price": 7.0, "market_cap": 10000000000, "market_cap_rank": 13},
            {"id": "chainlink", "symbol": "link", "name": "Chainlink", "image": "https://assets.coingecko.com/coins/images/877/large/chainlink-new-logo.png", "current_price": 14.0, "market_cap": 8000000000, "market_cap_rank": 14},
            {"id": "tron", "symbol": "trx", "name": "TRON", "image": "https://assets.coingecko.com/coins/images/1094/large/tron-logo.png", "current_price": 0.12, "market_cap": 10000000000, "market_cap_rank": 15},
            {"id": "matic-network", "symbol": "matic", "name": "Polygon", "image": "https://assets.coingecko.com/coins/images/4713/large/matic-token-icon.png", "current_price": 0.70, "market_cap": 7000000000, "market_cap_rank": 16},
            {"id": "bitcoin-cash", "symbol": "bch", "name": "Bitcoin Cash", "image": "https://assets.coingecko.com/coins/images/780/large/bitcoin-cash-circle.png", "current_price": 450.0, "market_cap": 9000000000, "market_cap_rank": 17},
            {"id": "near-protocol", "symbol": "near", "name": "NEAR Protocol", "image": "https://assets.coingecko.com/coins/images/10365/large/near.png", "current_price": 6.0, "market_cap": 6000000000, "market_cap_rank": 18},
            {"id": "uniswap", "symbol": "uni", "name": "Uniswap", "image": "https://assets.coingecko.com/coins/images/12504/large/uniswap-uni.png", "current_price": 10.0, "market_cap": 6000000000, "market_cap_rank": 19},
            {"id": "litecoin", "symbol": "ltc", "name": "Litecoin", "image": "https://assets.coingecko.com/coins/images/2/large/litecoin.png", "current_price": 80.0, "market_cap": 6000000000, "market_cap_rank": 20}
        ]

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
