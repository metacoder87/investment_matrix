from app.config import settings


class NewsConnector:
    """
    A connector for fetching news and social media sentiment from various sources.
    """

    def __init__(self):
        """
        Initializes the clients for NewsAPI.
        """
        pass

    def get_crypto_news(self, query: str = 'crypto', language: str = 'en', sort_by: str = 'relevancy', page_size: int = 20):
        """
        Fetches top headlines for a given query from NewsAPI.

        Args:
            query (str): The search query (e.g., 'bitcoin', 'ethereum').
            language (str): The language of the articles.
            sort_by (str): The order to sort the articles in.
            page_size (int): The number of results to return.

        Returns:
            A dictionary containing the news articles, or None if an error occurs.
        """
        if not settings.NEWS_API_KEY:
            return {"status": "disabled", "reason": "NEWS_API_KEY not set", "articles": []}

        try:
            from newsapi import NewsApiClient  # type: ignore
        except ImportError:
            return {"status": "disabled", "reason": "newsapi-python not installed", "articles": []}

        try:
            newsapi = NewsApiClient(api_key=settings.NEWS_API_KEY)
            return newsapi.get_everything(
                q=query,
                language=language,
                sort_by=sort_by,
                page_size=page_size,
            )
        except Exception as e:
            print(f"An error occurred while fetching news from NewsAPI: {e}")
            if "401" in str(e):
                print("Please ensure your NEWS_API_KEY is valid.")
            return {"status": "error", "reason": str(e), "articles": []}
