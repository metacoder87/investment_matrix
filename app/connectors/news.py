from .news_api import NewsConnector as NewsApiConnector
from .coinmarketcap import CoinMarketCapConnector
from .financialmodelingprep import FinancialModelingPrepConnector
from .newsdata_io import NewsDataIoConnector
from .coinpaprika import CoinPaprikaConnector
from .fundamental import CoinGeckoConnector

class News:
    def __init__(self):
        self.news_api_connector = NewsApiConnector()
        self.coinmarketcap_connector = CoinMarketCapConnector()
        self.financialmodelingprep_connector = FinancialModelingPrepConnector()
        self.newsdata_io_connector = NewsDataIoConnector()
        self.coinpaprika_connector = CoinPaprikaConnector()
        self.coingecko_connector = CoinGeckoConnector()

    def get_news(self, query: str):
        news_api_articles = self.news_api_connector.get_crypto_news(query=query)
        coinmarketcap_articles = self.coinmarketcap_connector.get_news(slug=query)
        financialmodelingprep_articles = self.financialmodelingprep_connector.get_crypto_news(symbol=query)
        newsdata_io_articles = self.newsdata_io_connector.get_crypto_news(query=query)
        coinpaprika_articles = self.coinpaprika_connector.get_news(coin_id=query)
        coingecko_updates = self.coingecko_connector.get_status_updates(coin_id=query)
        
        return {
            "news_api": news_api_articles,
            "coinmarketcap": coinmarketcap_articles,
            "financialmodelingprep": financialmodelingprep_articles,
            "newsdata_io": newsdata_io_articles,
            "coinpaprika": coinpaprika_articles,
            "coingecko": coingecko_updates,
        }
