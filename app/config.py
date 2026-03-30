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
    TRACK_TOP_N_COINS: int = Field(
        default=500,
        description="Number of top coins by market cap to automatically track and backfill on startup."
    )
    STREAM_EXCHANGE: str = "COINBASE"
    STREAM_EXCHANGES: str = Field(
        default="",
        description="Comma-separated exchanges to stream from (overrides STREAM_EXCHANGE when set). Example: COINBASE,BINANCE,KRAKEN",
    )
    STREAM_MAX_SYMBOLS_PER_EXCHANGE: int = Field(
        default=25,
        description="Safety cap to avoid subscribing to too many symbols per exchange in the zero-cost default stack.",
    )
    PRICE_EXCHANGE_PRIORITY: str = Field(
        default="binance,coinbase,kraken",
        description="Comma-separated exchange priority list for price data when exchange is auto.",
    )

    # Tick storage policy (TimescaleDB)
    TICK_RETENTION_YEARS: int = 3
    TICK_1S_RETENTION_YEARS: int = 5
    TICK_3S_RETENTION_YEARS: int = 7
    TICK_5S_RETENTION_YEARS: int = 10
    TICK_7S_RETENTION_YEARS: int = 15
    TICK_COMPRESS_AFTER_DAYS: int = 3
    TICK_FOCUS_WINDOW_MINUTES: int = 10

    # Import/download settings
    IMPORT_DATA_DIR: str = "data/imports"
    IMPORT_DOWNLOAD_CHUNK_BYTES: int = 1024 * 1024
    IMPORT_HTTP_TIMEOUT_SECONDS: int = 30

    # Optional scheduled imports (Celery beat)
    AUTO_IMPORT_ENABLED: bool = False
    AUTO_IMPORT_BINANCE_SYMBOLS: str = ""
    AUTO_IMPORT_BINANCE_KIND: str = "trades"
    AUTO_IMPORT_EXCHANGE: str = "binance"

    # Paper trading scheduler
    PAPER_SCHEDULER_ENABLED: bool = False
    PAPER_SCHEDULER_INTERVAL_SECONDS: int = 60

    # Exchange Specifics
    BINANCE_TLD: str = Field(
        default="com",
        description="Top-level domain for Binance API (com or us).",
    )

    # Security
    SECRET_KEY: str = Field(description="JWT Secret Key - REQUIRED. Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'")
    ENCRYPTION_KEY: str = Field(description="Fernet Key (base64) - REQUIRED. Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
    
    # CORS Configuration
    ALLOWED_ORIGINS: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated list of allowed CORS origins"
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
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )


settings = Settings()

