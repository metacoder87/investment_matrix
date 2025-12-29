from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Defaults are intentionally local-dev friendly so the repo can import/run/tests
    without requiring a pre-existing `.env` file.
    """

    # App / routing
    APP_NAME: str = "CryptoInsight"
    API_PREFIX: str = "/api"
    UI_PREFIX: str = "/ui"

    # Database Configuration (TimescaleDB/Postgres)
    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: str = "pass"
    POSTGRES_DB: str = "cryptoinsight"
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://user:pass@localhost:5432/cryptoinsight",
        description="SQLAlchemy database URL (sync).",
    )

    # Celery/Redis Configuration
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Streaming defaults
    CORE_UNIVERSE: str = "BTC-USD,ETH-USD,SOL-USD"
    STREAM_EXCHANGE: str = "COINBASE"
    STREAM_EXCHANGES: str = Field(
        default="",
        description="Comma-separated exchanges to stream from (overrides STREAM_EXCHANGE when set). Example: COINBASE,BINANCE,KRAKEN",
    )
    STREAM_MAX_SYMBOLS_PER_EXCHANGE: int = Field(
        default=25,
        description="Safety cap to avoid subscribing to too many symbols per exchange in the zero-cost default stack.",
    )

    # Exchange Specifics
    BINANCE_TLD: str = Field(
        default="com",
        description="Top-level domain for Binance API (com or us).",
    )

    # Optional API keys (plugins; keep empty by default for zero-cost core)
    NEWS_API_KEY: str = ""
    COINMARKETCAP_API_KEY: str = ""
    FINANCIALMODELINGPREP_API_KEY: str = ""
    NEWSDATAIO_API_KEY: str = ""
    COINPAPRIKA_API_KEY: str = ""
    STOCKGEIST_API_KEY: str = ""
    SANTIMENT_API_KEY: str = ""
    LUNARCRUSH_API_KEY: str = ""
    CRYPTOCOMPARE_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
