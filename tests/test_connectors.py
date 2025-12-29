from unittest.mock import patch
from app.connectors.fundamental import CoinGeckoConnector
from app.connectors.news import News

# --- Tests for CoinGeckoConnector ---

@patch('app.connectors.fundamental.CoinGeckoAPI')
def test_coingecko_connector_get_all_coins(MockCoinGeckoAPI):
    """
    Tests the get_all_coins method of the CoinGeckoConnector.
    """
    # Given
    mock_instance = MockCoinGeckoAPI.return_value
    mock_instance.get_coins_markets.return_value = [{'id': 'bitcoin', 'symbol': 'btc'}]
    
    connector = CoinGeckoConnector()

    # When
    result = connector.get_all_coins()

    # Then
    assert result is not None
    assert len(result) == 1
    assert result[0]['id'] == 'bitcoin'
    mock_instance.get_coins_markets.assert_called_once_with(vs_currency='usd')

@patch('app.connectors.fundamental.CoinGeckoAPI')
def test_coingecko_connector_ping(MockCoinGeckoAPI):
    """
    Tests the ping method of the CoinGeckoConnector.
    """
    # Given
    mock_instance = MockCoinGeckoAPI.return_value
    mock_instance.ping.return_value = {'gecko_says': '(V3) To the Moon!'}
    
    connector = CoinGeckoConnector()

    # When
    result = connector.ping()

    # Then
    assert result is True


# --- Tests for NewsConnector ---

@patch('app.connectors.news.NewsApiConnector')
@patch('app.connectors.news.CoinMarketCapConnector')
@patch('app.connectors.news.FinancialModelingPrepConnector')
@patch('app.connectors.news.NewsDataIoConnector')
@patch('app.connectors.news.CoinPaprikaConnector')
@patch('app.connectors.news.CoinGeckoConnector')
def test_news_hub_get_news(mock_coingecko, mock_coinpaprika, mock_newsdata_io, mock_financialmodelingprep, mock_coinmarketcap, mock_news_api):
    """
    Tests the get_news method of the News hub.
    """
    # Given
    mock_news_api.return_value.get_crypto_news.return_value = {'articles': [{'title': 'Crypto is booming'}]}
    mock_coinmarketcap.return_value.get_news.return_value = {'articles': [{'title': 'CMC loves crypto'}]}
    mock_financialmodelingprep.return_value.get_crypto_news.return_value = {'articles': [{'title': 'FMP loves crypto'}]}
    mock_newsdata_io.return_value.get_crypto_news.return_value = {'articles': [{'title': 'NewsData.io loves crypto'}]}
    mock_coinpaprika.return_value.get_news.return_value = {'articles': [{'title': 'CoinPaprika loves crypto'}]}
    mock_coingecko.return_value.get_status_updates.return_value = {'updates': [{'title': 'CoinGecko loves crypto'}]}
    
    hub = News()

    # When
    result = hub.get_news(query='bitcoin')

    # Then
    assert result is not None
    assert 'news_api' in result
    assert 'coinmarketcap' in result
    assert 'financialmodelingprep' in result
    assert 'newsdata_io' in result
    assert 'coinpaprika' in result
    assert 'coingecko' in result
    assert result['news_api']['articles'][0]['title'] == 'Crypto is booming'
    mock_news_api.return_value.get_crypto_news.assert_called_once_with(query='bitcoin')
    mock_coinmarketcap.return_value.get_news.assert_called_once_with(slug='bitcoin')
    mock_financialmodelingprep.return_value.get_crypto_news.assert_called_once_with(symbol='bitcoin')
    mock_newsdata_io.return_value.get_crypto_news.assert_called_once_with(query='bitcoin')
    mock_coinpaprika.return_value.get_news.assert_called_once_with(coin_id='bitcoin')
    mock_coingecko.return_value.get_status_updates.assert_called_once_with(coin_id='bitcoin')
