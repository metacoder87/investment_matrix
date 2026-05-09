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
    ENVIRONMENT: str = Field(
        default="local",
        description="Runtime environment: local, test, or production.",
    )

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

    # Exchange/source defaults
    PRIMARY_EXCHANGE: str = Field(
        default="kraken",
        description="Primary exchange id for market data, research snapshots, and paper-trading defaults.",
    )

    # Streaming defaults
    CORE_UNIVERSE: str = "BTC-USD,ETH-USD,SOL-USD"
    TRACK_TOP_N_COINS: int = Field(
        default=50,
        description="Number of top coins by market cap to automatically track and backfill on startup."
    )
    STREAM_EXCHANGE: str = "KRAKEN"
    STREAM_EXCHANGES: str = Field(
        default="",
        description="Comma-separated exchanges to stream from (overrides STREAM_EXCHANGE when set). Example: COINBASE,BINANCE,KRAKEN",
    )
    STREAM_MAX_SYMBOLS_PER_EXCHANGE: int = Field(
        default=25,
        description="Safety cap to avoid subscribing to too many symbols per exchange in the zero-cost default stack.",
    )
    STREAM_DYNAMIC_ENABLED: bool = Field(
        default=True,
        description="Enable dynamic websocket target allocation and rebalance commands.",
    )
    STREAM_REBALANCE_SECONDS: int = Field(
        default=60,
        description="How often the dynamic websocket allocator recalculates active stream targets.",
    )
    STREAM_SOURCE_PRIORITY: str = Field(
        default="kraken,coinbase,binance,okx,bybit,kucoin,gateio,bitfinex,cryptocom,gemini,bitstamp",
        description="Comma-separated free data source priority for websocket market data allocation.",
    )
    STREAM_MAX_CONNECTIONS_PER_SOURCE: int = Field(
        default=1,
        description="Safety cap for websocket connections per public source.",
    )
    STREAM_MAX_MESSAGES_PER_SECOND_PER_SOURCE: float = Field(
        default=250.0,
        description="Capacity-aware safety cap for expected websocket messages/sec per source.",
    )
    STREAM_REDIS_MAX_PENDING: int = Field(
        default=50_000,
        description="Redis pending message count where stream allocation starts demoting non-critical symbols.",
    )
    STREAM_WRITER_MAX_LAG_SECONDS: int = Field(
        default=120,
        description="Writer lag threshold where stream allocation starts demoting non-critical symbols.",
    )
    STREAM_DB_PRESSURE_HIGH_WATERMARK: float = Field(
        default=0.80,
        description="Capacity pressure level where dynamic allocation shifts from tick streams toward lower-resolution tiers.",
    )
    INGEST_CAPACITY_MONITOR_SECONDS: int = Field(
        default=60,
        description="How often ingestion telemetry samples Redis, writer, and Timescale health.",
    )
    TIER2_REST_GAP_FILL_ENABLED: bool = Field(
        default=True,
        description="Enable scheduled free REST recent-trade/OHLCV fills for non-streamed coverage tiers.",
    )
    TIER2_REST_GAP_FILL_SECONDS: int = Field(
        default=300,
        description="How often Tier 2 REST gap-fill workers run.",
    )
    DEX_CONTEXT_REFRESH_SECONDS: int = Field(
        default=900,
        description="How often free DEX context/discovery workers run.",
    )
    MARKET_ACTIVATION_ENABLED: bool = Field(
        default=True,
        description="Enable broad conversion of discovered markets into tiered coverage candidates.",
    )
    MARKET_ACTIVATION_INTERVAL_SECONDS: int = Field(
        default=600,
        description="How often discovered markets are activated into tiered coverage.",
    )
    MARKET_ACTIVATION_BATCH_SIZE: int = Field(
        default=5000,
        description="Maximum discovered markets evaluated by one activation pass.",
    )
    MARKET_ACTIVATION_QUEUE_LIMIT: int = Field(
        default=200,
        description="Maximum REST/OHLCV coverage jobs queued by one activation pass.",
    )
    MARKET_ACTIVATION_BACKFILL_DAYS: int = Field(
        default=7,
        description="Initial OHLCV backfill window for newly activated markets.",
    )
    MARKET_ACTIVATION_TIMEFRAME: str = Field(
        default="1m",
        description="Default candle timeframe for broad market activation backfills.",
    )
    STREAM_USER_LOCKED_SYMBOLS: str = Field(
        default="",
        description="Comma-separated BASE-QUOTE symbols that should be streamed first when supported.",
    )
    STREAM_USER_BLOCKED_SYMBOLS: str = Field(
        default="",
        description="Comma-separated BASE-QUOTE symbols that should not be streamed dynamically.",
    )
    DEX_INGEST_ENABLED: bool = Field(
        default=True,
        description="Enable free DEX aggregator discovery/context ingestion.",
    )
    ONCHAIN_RPC_URLS: str = Field(
        default="",
        description="Optional comma-separated free RPC URLs for selected on-chain pool tailing.",
    )
    PRICE_EXCHANGE_PRIORITY: str = Field(
        default="kraken,coinbase,binance",
        description="Comma-separated exchange priority list for price data when exchange is auto.",
    )
    MARKET_UNIVERSE_TARGET: int = Field(
        default=750,
        description="Target number of exchange-supported markets to discover/backfill for the market dashboard.",
    )
    MARKET_DEFAULT_PAGE_SIZE: int = Field(
        default=500,
        description="Default number of assets returned by high-density market views.",
    )
    KRAKEN_BACKFILL_BATCH_SIZE: int = Field(
        default=50,
        description="Maximum Kraken markets queued by one backfill operation.",
    )
    KRAKEN_BACKFILL_MAX_ACTIVE: int = Field(
        default=8,
        description="Maximum active Kraken backfill tasks before queuing more is skipped.",
    )
    KRAKEN_STREAM_TOP_N: int = Field(
        default=100,
        description="Maximum number of Kraken markets to stream live by default.",
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

    # Local AI crew runtime. Disabled by default so the app remains usable
    # without Ollama or any local model installed.
    CREW_ENABLED: bool = False
    CREW_LLM_PROVIDER: str = "ollama"
    CREW_LLM_BASE_URL: str = "http://host.docker.internal:11434"
    CREW_LLM_MODEL: str = "llama3.1:8b"
    CREW_MAX_SYMBOLS_PER_RUN: int = 10
    CREW_LLM_TIMEOUT_SECONDS: int = 600
    CREW_RESEARCH_ENABLED: bool = False
    CREW_TRIGGER_MONITOR_ENABLED: bool = False
    CREW_RESEARCH_INTERVAL_SECONDS: int = 300
    CREW_TRIGGER_POLL_SECONDS: int = 5
    CREW_FORMULA_LEARNING_INTERVAL_SECONDS: int = 3600
    CREW_BANKROLL_RESET_DRAWDOWN_PCT: float = 0.95
    CREW_DEFAULT_STARTING_BANKROLL: float = 10_000.0

    # Exchange Specifics
    BINANCE_TLD: str = Field(
        default="com",
        description="Top-level domain for Binance API (com or us).",
    )
    KRAKEN_API_KEY: str = Field(
        default="",
        description="Optional Kraken API key. Not used for paper trading or real order placement.",
    )
    KRAKEN_API_SECRET: str = Field(
        default="",
        description="Optional Kraken API secret. Not used for paper trading or real order placement.",
    )

    # Security
    SECRET_KEY: str = Field(
        default="",
        description="JWT secret. Leave blank only for local/CI dev fallback behavior.",
    )
    ENCRYPTION_KEY: str = Field(
        default="",
        description="Fernet key. Leave blank only for local/CI dev fallback behavior.",
    )
    ADMIN_KEY: str = Field(
        default="",
        description="Admin API key for protected system routes.",
    )
    AUTH_COOKIE_SECURE: bool | None = Field(
        default=None,
        description="Set auth cookies with the Secure attribute. Defaults to true outside local/test.",
    )
    AUTH_COOKIE_SAMESITE: str = Field(
        default="",
        description="Auth cookie SameSite policy: lax, strict, or none. Defaults to strict outside local/test.",
    )
    
    # CORS Configuration
    ALLOWED_ORIGINS: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated list of allowed CORS origins"
    )

    # Optional API keys (plugins; keep empty by default for zero-cost core)
    NEWS_API_KEY: str = ""
    COINMARKETCAP_API_KEY: str = ""
    COINGECKO_DEMO_API_KEY: str = ""
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

