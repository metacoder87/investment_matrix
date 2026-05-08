# Investment Matrix Free Data Ingestion Strategy

## Summary

Investment Matrix will use a zero-paid, layered ingestion strategy. No paid plans or expiring trials are required. Public no-signup endpoints are enabled by default, and free API-key tiers are optional enhancements when the user configures keys.

The target data picture is:

- Tick-level public websocket trades for the highest-value centralized exchange pairs.
- L1 quote/book-ticker streams for spread and liquidity where available.
- CCXT REST recent-trade and OHLCV gap filling for lower-priority CEX markets.
- DEX/on-chain coverage through free aggregators at their natural resolution.
- Optional true on-chain event tailing only for selected high-priority pools when free RPC URLs are configured.
- Dynamic stream allocation from a hybrid score that combines user preference, market opportunity, model/paper-trading edge, liquidity, volatility, spread, portfolio exposure, and data gaps.

## Free Source Layers

### Tier 1: Live CEX Trades

Primary tick-level streaming comes from public websocket trade channels. The first implementation targets these exchanges:

- Existing: Kraken, Coinbase, Binance.
- New: OKX, Bybit, KuCoin, Gate.io, Bitfinex, Crypto.com, Gemini, Bitstamp.

Each adapter normalizes trade events into the existing Redis stream and `ticks`/`market_trades` storage path:

- `exchange`
- `symbol`
- `ts`
- `recv_ts`
- `price`
- `amount`
- `side`
- `trade_id`
- optional raw/source metadata

### Tier 2: Live Quotes

Where a free public websocket source exposes best bid/ask or book ticker data, adapters also publish L1 quote events. Quotes are used for spread-aware scoring and freshness monitoring, not as a substitute for trades.

Quote events persist to `market_quotes` and cache latest values in Redis under exchange-aware keys.

### Tier 3: REST Gap Fill

CCXT remains the main REST abstraction for:

- Exchange market discovery.
- OHLCV candle backfill.
- Recent-trade gap fill when the venue supports it.

Binance Vision remains the preferred free historical tick source for Binance spot pairs. The importer must auto-detect millisecond versus microsecond timestamps because Binance historical spot files changed timestamp precision after 2025.

### Tier 4: Metadata, Fundamentals, and DEX Context

Metadata and non-tick context come from:

- CoinGecko public/demo API for coin metadata and market rankings.
- CoinPaprika for free coin/event metadata.
- CoinMarketCap free API-key tier when configured.
- DeFiLlama for protocol, DEX volume, price, stablecoin, and yield context.
- DEX Screener for token/pair discovery, liquidity, volume, boosts, and trending signals.
- GeckoTerminal for free pool and OHLCV coverage under public rate limits.

DEX aggregator data is lower-resolution by default. It should not be labeled as tick-level unless an on-chain event tailer is explicitly configured for the pool.

## Implementation Phases

### Phase 1: Source Health and Schema

Add persistent records for:

- `data_source_health`: websocket/rest capability, enabled state, rate-limit profile, reconnect count, messages/sec, last successful event, last error, latency, and metadata.
- `stream_targets`: active and candidate websocket targets with score, rank, status, user preference, scoring details, and timestamps.
- `market_quotes`: L1 quote events with bid, ask, sizes, mid, spread, and received timestamp.
- `dex_pools`: optional DEX pool metadata for aggregator-backed markets.

Keep existing `ticks`, `market_trades`, `prices`, `ExchangeMarket`, and `AssetDataStatus` as the core time-series and market state.

### Phase 2: Websocket Expansion

Refactor the streamer command path from subscribe-only to:

- `subscribe`
- `unsubscribe`
- `replace_set`

Each streamer should maintain its active symbols and format dynamic exchange-specific subscribe/unsubscribe payloads. A source that cannot dynamically unsubscribe should reconnect with the replacement set.

Add adapters for OKX, Bybit, KuCoin, Gate.io, Bitfinex, Crypto.com, Gemini, and Bitstamp. Each adapter must:

- Normalize exchange symbols to the app's `BASE-QUOTE` convention.
- Parse documented public trade payloads.
- Publish standardized trade events.
- Optionally publish quote events when a source supports L1 data.
- Degrade independently when a venue rejects a symbol or disconnects.

### Phase 3: Dynamic Allocation

Add `stream_allocator` as a Celery task scheduled every `STREAM_REBALANCE_SECONDS` when `STREAM_DYNAMIC_ENABLED=true`.

Default score weights:

- 30% paper/model edge.
- 20% liquidity.
- 15% volatility.
- 10% spread quality.
- 10% data-gap/freshness need.
- 10% portfolio/watchlist interest.
- 5% source reliability.

User preference overrides:

- Locked symbols are streamed first when the market exists and the source is healthy.
- Blocked symbols are never streamed.
- Boosted symbols receive a score increase but still respect source and capacity limits.

Allocator responsibilities:

- Discover candidate markets from `ExchangeMarket`.
- Combine latest coin metadata, price rows, quotes, source health, and user preferences.
- Write ranked `stream_targets` rows.
- Publish per-exchange `replace_set` commands to `streamer:commands`.
- Explain each score in `score_details_json`.
- Assign each target to a coverage tier: `tick_stream`, `quote_stream`, `rest_gap_fill`, `ohlcv_only`, `dex_context_only`, or `blocked`.
- Demote marginal symbols when Redis lag, writer lag, or Timescale pressure rises instead of removing them from coverage entirely.

### Phase 3B: Capacity and Timescale Rollups

Make TimescaleDB the primary high-volume decision store:

- Keep raw trades in `ticks` as the primary tick-level table.
- Keep `market_trades` as compatibility stream history.
- Convert `market_quotes` to a Timescale hypertable with compression and short raw retention.
- Maintain tick rollups at `1s`, `5s`, `1m`, and `5m` where TimescaleDB is available.
- Maintain quote/spread rollups at `1m` and `5m`.
- Prefer raw ticks for hot recent queries, Timescale rollups for longer ranges, then compatibility trades and OHLCV candles.

Add an ingestion telemetry loop that samples Redis stream length, consumer lag, writer lag, insert throughput, source freshness, and Timescale health. The allocator uses this telemetry as a hard capacity signal.

### Phase 4: Operations APIs

Add:

- `GET /api/operations/data-sources`
- `GET /api/operations/stream-targets`
- `POST /api/operations/stream-targets/preferences`
- `POST /api/operations/market/sync-all`

These endpoints expose source health, ranked stream targets, preference updates, and multi-exchange market discovery.

### Phase 5: Verification

Tests must cover:

- Websocket parser behavior for every adapter.
- Symbol normalization across CEX quote variants and DEX token addresses.
- Allocator scoring, locks, blocks, health penalties, and exchange caps.
- Mixed trade/quote publishing and writer persistence.
- Binance Vision millisecond/microsecond timestamp auto-detection.
- Operations endpoints for source health and stream targets.
- Candle loading still preferring raw ticks, then market trades, then stored candles.

## Operational Defaults

New settings:

- `STREAM_DYNAMIC_ENABLED=true`
- `STREAM_REBALANCE_SECONDS=60`
- `STREAM_SOURCE_PRIORITY=kraken,coinbase,binance,okx,bybit,kucoin,gateio,bitfinex,cryptocom,gemini,bitstamp`
- `STREAM_MAX_SYMBOLS_PER_EXCHANGE=25`
- `STREAM_MAX_CONNECTIONS_PER_SOURCE=1`
- `STREAM_MAX_MESSAGES_PER_SECOND_PER_SOURCE=250`
- `STREAM_REDIS_MAX_PENDING=50000`
- `STREAM_WRITER_MAX_LAG_SECONDS=120`
- `STREAM_DB_PRESSURE_HIGH_WATERMARK=0.80`
- `INGEST_CAPACITY_MONITOR_SECONDS=60`
- `TIER2_REST_GAP_FILL_ENABLED=true`
- `TIER2_REST_GAP_FILL_SECONDS=300`
- `STREAM_USER_LOCKED_SYMBOLS=`
- `STREAM_USER_BLOCKED_SYMBOLS=`
- `DEX_INGEST_ENABLED=true`
- `DEX_CONTEXT_REFRESH_SECONDS=900`
- `ONCHAIN_RPC_URLS=`
- `COINGECKO_DEMO_API_KEY=`

Existing optional keys remain supported:

- `COINMARKETCAP_API_KEY`
- `COINPAPRIKA_API_KEY`
- `CRYPTOCOMPARE_API_KEY`

## Source References

Primary public docs used for the implementation plan:

- Binance Spot websocket streams and Binance public data.
- Coinbase Exchange websocket channels.
- Kraken WebSocket v2 trade channel.
- OKX public websocket API.
- Bybit public trade websocket.
- KuCoin websocket public token and market match channels.
- Gate.io spot websocket `spot.trades`.
- Bitfinex public websocket trades.
- Crypto.com Exchange websocket subscriptions.
- Gemini public market data websocket.
- Bitstamp websocket live trades.
- DEX Screener API reference.
- GeckoTerminal/CoinGecko API docs.
- DeFiLlama API docs.
- CoinPaprika API docs.
