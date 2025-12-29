<![CDATA[<div align="center">

# 🚀 CryptoInsight

### *Local-First, Profit-First Crypto Market Intelligence Terminal*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-pg16-FFA500.svg)](https://www.timescale.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Live market streaming • Deep analysis • TradingView-style charts • Paper trading • Zero-cost data**

[Quick Start](#-quick-start) • [Features](#-features) • [Architecture](#-architecture) • [API Reference](#-api-reference) • [Roadmap](#-roadmap)

</div>

---

## 📖 Overview

**CryptoInsight** (formerly Investment Matrix) is a **high-performance, self-hosted cryptocurrency market analysis platform** designed for serious traders and developers. Built with a focus on **depth of analysis + speed of interaction**, it provides:

- 📡 **Real-time tick-level streaming** from major exchanges (Coinbase, Binance, Kraken)
- 📊 **TradingView-style interactive charts** with lightweight-charts library
- 🧠 **Deep Technical Analysis** with 50+ indicators via pandas-ta
- 📉 **Quantitative Risks** including Sharpe, Sortino ratios and customized volatility metrics
- 💾 **Local-first architecture** - your data stays on your machine
- 💰 **Zero-cost data sources** - uses free exchange APIs by default
- 🔒 **Security-first design** - keys never committed; OS keychain storage

---

## ✨ Features

### ✅ Implemented Features

| Feature | Description | Status |
|---------|-------------|--------|
| **Live Market Streaming** | Real-time tick data via WebSockets from Coinbase (expandable to Binance, Kraken) | ✅ Complete |
| **Next.js Frontend** | Modern React-based UI with Tailwind CSS, glassmorphism design, and neon accents | ✅ Complete |
| **Interactive Charts** | TradingView-style charts using `lightweight-charts` with zoom/pan | ✅ Complete |
| **FastAPI Backend** | High-performance async REST API with OpenAPI documentation | ✅ Complete |
| **TimescaleDB Storage** | Time-series optimized PostgreSQL for efficient data storage | ✅ Complete |
| **Redis Caching** | Hot cache + Redis Streams for real-time data distribution | ✅ Complete |
| **Celery Workers** | Background task processing for data ingestion and backfills | ✅ Complete |
| **Docker Compose Stack** | One-command deployment of all 7 services | ✅ Complete |
| **Alembic Migrations** | Database schema management with version control | ✅ Complete |
| **Market Data API** | Endpoints for ticks, candles, series, coverage, and coin lists | ✅ Complete |
| **Deep Analysis** | 50+ Technical Indicators, Risk Metrics, and Fundamental/Sentiment Data | ✅ Complete |
| **CoinGecko Integration** | Top 100 market snapshot and coin metadata | ✅ Complete |
| **Test Suite** | Pytest-based tests for API, analysis, and connectors | ✅ Complete |

### 🔨 Partially Complete

| Feature | Description | Status |
|---------|-------------|--------|
| **Multi-Exchange Support** | Streaming from COINBASE works; BINANCE/KRAKEN configs ready | 🔨 In Progress |
| **Solara UI (Legacy)** | Original Python-based dashboard; replaced by Next.js | ⚠️ Legacy |

### 🗓️ Planned Features

| Feature | Description | Phase |
|---------|-------------|-------|
| **Backtesting Engine** | Historical strategy testing with fees/slippage modeling | Phase 4 |
| **Paper Trading** | Simulated trading with live market data | Phase 4 |
| **Live Trading** | Secure exchange execution with kill switches | Phase 5 |
| **ML Predictions** | Temporal Fusion Transformer (TFT) forecasting | Phase 6 |
| **Alert System** | Price, volume, and indicator-based notifications | Phase 2 |
| **Watchlists** | Custom asset tracking and organization | Phase 2 |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐  │
│  │   Next.js Frontend      │    │     Solara UI (Legacy)                  │  │
│  │   Port: 3000            │    │     Port: 8000/ui                       │  │
│  │   • Tailwind CSS        │    │     • Python-native                     │  │
│  │   • lightweight-charts  │    │     • Plotly Resampler                  │  │
│  │   • WebSocket client    │    │                                         │  │
│  └────────────┬────────────┘    └─────────────────────────────────────────┘  │
└───────────────│──────────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────────┐
│                              API LAYER                                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    FastAPI Server (Port 8000)                           │ │
│  │  /api/health ─────────────► Health Check                                │ │
│  │  /api/coins ──────────────► CoinGecko Market Data                       │ │
│  │  /api/market/latest/{sym}─► Redis Latest Tick                           │ │
│  │  /api/market/trades/{sym}─► TimescaleDB Trades                          │ │
│  │  /api/market/candles ─────► OHLCV Aggregation                           │ │
│  │  /api/market/series ──────► Downsampled Price Series                    │ │
│  │  /api/coin/{sym}/analysis─► Technical Indicators (50+)                  │ │
│  │  /api/coin/{sym}/quant────► Quantitative Risk Metrics                   │ │
│  │  /api/coin/{sym}/sentiment► Sentiment & Fundamentals                    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────────┐
│                              DATA LAYER                                       │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │    Redis         │  │   TimescaleDB    │  │     Celery Workers       │   │
│  │    Port: 6379    │  │   Port: 5432     │  │                          │   │
│  │                  │  │                  │  │  • Ingestion Tasks       │   │
│  │  • Hot Cache     │  │  • market_trades │  │  • OHLCV Backfills       │   │
│  │  • Streams       │  │  • prices        │  │  • Scheduled Jobs        │   │
│  │  • Latest Ticks  │  │  • coins         │  │                          │   │
│  └────────▲─────────┘  └────────▲─────────┘  └──────────────────────────┘   │
└───────────│─────────────────────│────────────────────────────────────────────┘
            │                     │
┌───────────│─────────────────────│────────────────────────────────────────────┐
│           │    STREAMING LAYER  │                                             │
├───────────│─────────────────────│────────────────────────────────────────────┤
│  ┌────────┴─────────┐  ┌────────┴─────────┐                                   │
│  │    Streamer      │  │     Writer       │                                   │
│  │                  │  │                  │                                   │
│  │  Exchange WS ───►│──│──► Redis Streams │───► TimescaleDB                   │
│  │  (Coinbase)      │  │     market_ticks │                                   │
│  └──────────────────┘  └──────────────────┘                                   │
└──────────────────────────────────────────────────────────────────────────────┘

                         EXTERNAL DATA SOURCES
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │   Coinbase   │  │   Binance    │  │    Kraken    │  │  CoinGecko   │
    │   WebSocket  │  │   WebSocket  │  │   WebSocket  │  │   REST API   │
    └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

### 🐳 Docker Services

| Service | Image/Build | Port | Purpose |
|---------|-------------|------|---------|
| `db` | `timescale/timescaledb-ha:pg16` | 5432 | Time-series database |
| `redis` | `redis:alpine` | 6379 | Cache + stream bus |
| `migrate` | Custom build | - | One-time Alembic migrations |
| `api` | Custom build | 8000 | FastAPI + Solara server |
| `worker` | Custom build | - | Celery background tasks |
| `streamer` | Custom build | - | Exchange WebSocket ingestion |
| `writer` | Custom build | - | Redis → TimescaleDB persistence |
| `frontend` | Custom build | 3000 | Next.js web application |

---

## 🚀 Quick Start

### Prerequisites

- **Docker Desktop** with Docker Compose
- **8GB RAM** minimum (16GB recommended)
- **Stable internet** for initial image pulls and market data

### One-Command Launch (Docker)

```bash
# Clone the repository
git clone https://github.com/your-username/investment_matrix.git
cd investment_matrix

# Copy environment template
cp .env.example .env

# Launch all services
docker compose up --build
```

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| 🖥️ **Frontend UI** | http://localhost:3000 | Next.js Dashboard |
| 📚 **API Docs** | http://localhost:8000/api/docs | OpenAPI/Swagger |
| 🔧 **Legacy UI** | http://localhost:8000/ui | Solara Dashboard |
| 🏥 **Health Check** | http://localhost:8000/api/health | Service Status |

---

## 💻 Local Development

### Python Backend Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start TimescaleDB + Redis (Docker)
docker compose up db redis -d

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload

# Start Celery worker (new terminal)
celery -A celery_app worker --loglevel=info

# Start streamer (new terminal)
python -m app.streamer
```

### Next.js Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file from `.env.example`:

```env
# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════
POSTGRES_USER=user
POSTGRES_PASSWORD=pass
POSTGRES_DB=cryptoinsight
DATABASE_URL=postgresql+psycopg2://user:pass@db:5432/cryptoinsight

# ═══════════════════════════════════════════════════════════════
# REDIS / CELERY
# ═══════════════════════════════════════════════════════════════
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# ═══════════════════════════════════════════════════════════════
# STREAMING
# ═══════════════════════════════════════════════════════════════
CORE_UNIVERSE=BTC-USD,ETH-USD,SOL-USD
STREAM_EXCHANGE=COINBASE
# STREAM_EXCHANGES=COINBASE,BINANCE,KRAKEN  # Multi-exchange support
# BINANCE_TLD=us  # Set to 'us' for Binance US

# ═══════════════════════════════════════════════════════════════
# OPTIONAL API KEYS (Zero-cost core works without these)
# ═══════════════════════════════════════════════════════════════
NEWS_API_KEY=
COINMARKETCAP_API_KEY=
```

### Local Development Override

For non-Docker development, create `.env.local`:

```env
DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/cryptoinsight
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

---

## 📡 API Reference

### Health & Metadata

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Service health check |
| `GET` | `/api/exchanges` | Supported exchanges list |
| `GET` | `/api/coins` | Top 100 market snapshot |

### Market Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/market/latest/{symbol}` | Latest tick from Redis |
| `GET` | `/api/market/latest/{exchange}/{symbol}` | Latest tick per exchange |
| `GET` | `/api/market/trades/{symbol}` | Recent persisted trades |
| `GET` | `/api/market/series/{exchange}/{symbol}` | Downsampled price series |
| `GET` | `/api/market/candles/{exchange}/{symbol}` | OHLCV candles (`?timeframe=1m`) |
| `GET` | `/api/market/coverage/{exchange}/{symbol}` | Data coverage stats |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/coin/{symbol}/analysis` | TA indicators (RSI, Stoch, TSI, etc.) |
| `GET` | `/api/coin/{symbol}/quant` | Risk metrics (Sharpe, Sortino, Drawdown) |
| `GET` | `/api/coin/{coin_id}/fundamentals` | Market Cap, FDV, Supply stats |
| `GET` | `/api/coin/{query}/sentiment` | Sentiment scores & Fear/Greed Index |

### Ingestion

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ingest/coins` | Queue CoinGecko coin list |
| `POST` | `/api/ingest/prices/{symbol}` | Queue OHLCV backfill via CCXT |
| `GET` | `/api/ingest/status/{task_id}` | Celery task status |

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_api.py -v
```

### Test Categories

- `test_api.py` - API endpoint tests
- `test_analysis.py` - Technical analysis engine
- `test_connectors.py` - Data source connectors
- `test_market_*.py` - Market data endpoints

---

## 🗺️ Roadmap

### Phase 0: Foundation ✅
> *Make the repo coherent and runnable end-to-end*

- [x] One-command Docker Compose stack
- [x] Alembic migrations as schema source-of-truth
- [x] Free-first data strategy (no `ccxt.pro`)
- [x] FastAPI + Next.js architecture
- [x] Real-time streaming via WebSockets

### Phase 1: Reliable Ingestion 🔨
> *Build trust in the data pipeline*

- [x] Core universe tick streaming (Coinbase)
- [ ] Multi-exchange streaming (Binance, Kraken)
- [ ] Adaptive polling for long-tail assets
- [ ] Data quality checks + gap detection

### Phase 2: TradingView-Feel UI 🗓️
> *Fast, flashy, professional experience*

- [ ] Watchlists with custom organization
- [ ] Coin detail pages with multi-panel charts
- [ ] Volume anomaly scanner
- [ ] In-app alert system

### Phase 3: Deep Analysis 🗓️
> *The analytical edge*

- [ ] Feature store + indicator library
- [ ] Signal explanations ("why" panel)
- [ ] Portfolio/risk analytics (VaR, drawdown)

### Phase 4: Backtesting + Paper Trading 🗓️
> *Profit discipline before real money*

- [ ] Backtest engine with fees/slippage
- [ ] Paper trading with live feeds
- [ ] Strategy performance dashboards
- [ ] Promotion gates (min trades, max DD)

### Phase 5: Live Trading 🗓️
> *Secure, gated execution*

- [ ] OS keychain key management
- [ ] Exchange execution routing
- [ ] Kill switch + risk controls
- [ ] Fee/depth-aware order placement

### Phase 6: ML Integration 🗓️
> *Optional, advanced predictions*

- [ ] Dataset builder + baseline models
- [ ] TFT/Transformer forecasting
- [ ] ONNX inference optimization
- [ ] Champion/challenger registry

---

## 🛠️ Troubleshooting

### Docker Issues

<details>
<summary><strong>❌ Build fails with EOF</strong></summary>

This is usually a transient network issue. Try:

```bash
docker compose build --no-cache --progress=plain
docker compose pull  # If image pulls fail
```

Ensure Docker Desktop has internet access (VPN/proxy can interfere).
</details>

<details>
<summary><strong>❌ Module not found: Can't resolve 'date-fns'</strong></summary>

Old `node_modules` volume is stale. Fix:

```bash
docker compose down -v  # ⚠️ Removes DB data
docker compose up --build
```

To preserve DB data, manually remove only the frontend volume.
</details>

<details>
<summary><strong>❌ Windows pipe/file not found errors</strong></summary>

1. Ensure Docker Desktop is **running** (check system tray)
2. Restart Docker Desktop
3. Run `docker context use default` in PowerShell
4. Fallback: Run services locally without Docker
</details>

### Data Issues

<details>
<summary><strong>❌ Charts show no data</strong></summary>

1. Check if streamer is running: `docker compose logs streamer`
2. Verify Redis has data: Check `latest:*` keys
3. Confirm writer is persisting: `docker compose logs writer`
4. Wait 30-60 seconds after startup for initial data
</details>

### API Issues

<details>
<summary><strong>❌ 404 on API endpoints</strong></summary>

Ensure you're using the correct base path:
- API endpoints: `http://localhost:8000/api/...`
- UI: `http://localhost:3000` (Next.js) or `http://localhost:8000/ui` (Solara)
</details>

---

## 🔒 Security Notes

> [!CAUTION]
> **Do not commit real API keys or secrets!**

- Use `.env.local` for local overrides (gitignored)
- Production keys go in OS keychain via `keyring` library
- Live trading is **disabled by default** and gated behind safety checks
- Exchange API keys should have **withdrawals disabled**

---

## 📁 Project Structure

```
investment_matrix/
├── app/                        # FastAPI backend
│   ├── main.py                 # API entry point
│   ├── analysis.py             # Technical indicators
│   ├── streamer.py             # WebSocket ingestion
│   ├── writer.py               # Redis → DB persistence
│   ├── connectors/             # Exchange/data connectors
│   ├── models/                 # SQLAlchemy models
│   └── streaming/              # Multi-exchange streaming
├── frontend/                   # Next.js application
│   ├── src/
│   │   ├── app/                # Pages (market, portfolio, settings)
│   │   ├── components/         # React components
│   │   └── utils/              # Helper functions
│   └── package.json
├── celery_worker/              # Background task definitions
├── alembic/                    # Database migrations
├── tests/                      # Pytest test suite
├── docker-compose.yml          # Service orchestration
├── requirements.txt            # Python dependencies
└── .env.example                # Environment template
```

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ⚠️ Disclaimer

> [!WARNING]
> **This software is for educational and research purposes only.** No trading strategy guarantees profits. Cryptocurrency markets are highly volatile, and real trading can result in significant financial losses. Always:
> - Use paper trading first
> - Never invest more than you can afford to lose
> - Validate all strategies with rigorous backtesting
> - Understand the risks before enabling live trading

---

<div align="center">

**Built with ❤️ for the crypto community**

[⬆ Back to Top](#-cryptoinsight)

</div>
]]>
