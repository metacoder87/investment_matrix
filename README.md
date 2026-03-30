# CryptoInsight | Institutional-Grade Algorithmic Trading Platform

**A high-performance, local-first financial intelligence terminal designed for sub-millisecond data ingestion, real-time analytics, and automated trading.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-black.svg)](https://nextjs.org/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-pg16-FFA500.svg)](https://www.timescale.com/)
[![Redis](https://img.shields.io/badge/Redis-7.x-red.svg)](https://redis.io/)
[![Celery](https://img.shields.io/badge/Celery-5.x-37814A.svg)](https://docs.celeryq.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey.svg)](LICENSE)

---

## 🚀 Executive Summary

CryptoInsight is a self-hosted, simplified institutional trading platform. Unlike retail tools that rely on third-party aggregators, this system ingests raw tick data directly from exchange WebSockets, normalizes it into a unified schema, and stores it in a time-series optimized database (TimescaleDB).

Core capabilities:
*   **Tick-Level Fidelity**: Captures every trade for granular backtesting, not just OHLCV candles.
*   **Event-Driven Architecture**: Uses Redis Streams and Celery to decouple ingestion from analysis.
*   **Hybrid Storage**: Combines in-memory caching (Redis) for live views with columnar storage (TimescaleDB) for historical analysis.
*   **Modern UI**: A premium Next.js frontend featuring real-time, hardware-accelerated charting.

---

## 🏗 System Architecture

The platform is architected as a set of decoupled microservices, prioritizing fault tolerance and scalability.

```mermaid
graph TD
    subgraph "Ingestion Layer"
        WS[WebSocket Streamers] --"Standardized Ticks"--> Redis(Redis Streams)
    end

    subgraph "Persistence Layer"
        Redis --"Async Write"--> Writer[Writer Service]
        Writer --"Batch Insert"--> TDB[(TimescaleDB)]
    end

    subgraph "Application Layer"
        API[FastAPI Backend] --"Query"--> TDB
        API --"Cache Hit"--> Redis
        Worker[Celery Worker] --"Background Jobs"--> API
    end

    subgraph "Presentation Layer"
        UI[Next.js Frontend] --"REST / WS"--> API
    end
```

### 1. Data Ingestion (Streamers)
Standalone Python services that maintain persistent WebSocket connections to exchanges (Coinbase, Binance, Kraken). They handle reconnection logic, message normalization, and publishing to the dedicated Redis stream.

### 2. Persistence & Storage
*   **TimescaleDB**: Used for long-term storage. "Hypertables" automatically partition data by time, ensuring constant-time insertion performance even as datasets grow to terabytes.
*   **Redis**: Serves as both the hot message bus for live data and a look-aside cache for API responses (e.g., "latest price" queries).

### 3. Asynchronous Analysis
Celery workers handle computationally intensive tasks such as technical indicator calculation, rolling window aggregations, and historical measurement, preventing the main API thread from blocking.

---

## 🛠 Technology Stack

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Backend API** | **FastAPI** | High-performance async REST API & WebSockets. |
| **Database** | **TimescaleDB** (PostgreSQL) | Time-series storage with continuous aggregates. |
| **Caching/Broker** | **Redis** | Pub/Sub for live ticks, task queue for Celery. |
| **Task Queue** | **Celery** | Distributed task execution & scheduling. |
| **Frontend** | **Next.js** (React) | Server-side rendered, responsive UI. |
| **Charting** | **Lightweight Charts** | High-performance Canvas-based financial charts. |
| **Containerization** | **Docker Compose** | Orchestration of all services. |

---

## ⚡ Quick Start

### Prerequisites
*   **Docker Desktop** (running)
*   **Git**

### 1. Clone & Configure
```bash
git clone https://github.com/your-username/investment_matrix.git
cd investment_matrix
copy .env.example .env
```
*Edit `.env` if you need to enable optional data sources (e.g., Binance US).*

### 2. Launch with Docker (Recommended)
This brings up the entire stack: Database, Cache, API, Workers, Streamers, and Frontend.

```bash
docker compose up --build -d
```
*   **Frontend**: [http://localhost:3000](http://localhost:3000)
*   **API Docs**: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
*   **Health Check**: [http://localhost:8000/api/health](http://localhost:8000/api/health)

### 3. Run Database Migrations
If the container does not auto-migrate on first launch:
```bash
docker compose up migrate
```

---

## 💻 Local Development (Windows)

For developers who want to run the Python services locally while keeping infrastructure (DB/Redis) in Docker.

### 1. Start Infrastructure Only
```powershell
docker compose up db redis -d
```

### 2. Setup Python Environment
```powershell
# Create venv
python -m venv .venv

# Activate (Windows Powershell)
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env.local` file to point to localhost ports instead of Docker service names:
```ini
POSTGRES_USER=user
POSTGRES_PASSWORD=pass
POSTGRES_DB=cryptoinsight
DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/cryptoinsight
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### 4. Run Services
You will need multiple terminal tabs:

**Tab 1: API Server**
```powershell
uvicorn app.main:app --reload --env-file .env.local
```

**Tab 2: Celery Worker**
```powershell
celery -A celery_app:celery_app worker --loglevel=info --pool=solo
```

**Tab 3: Streamer**
```powershell
python -m app.streamer
```

**Tab 4: Writer**
```powershell
python -m app.writer
```

**Tab 5: Frontend**
```powershell
cd frontend
npm install
npm run dev
```

---

## 🛣 Roadmap

### Phase 1: Foundation (Current)
*   [x] Real-time WebSocket ingestion (Coinbase, Kraken, Binance).
*   [x] TimescaleDB schema with compression policies.
*   [x] Next.js Dashboard with live ticking charts.

### Phase 2: Intelligence & Analysis
*   [ ] Integration of `TA-Lib` for server-side indicator calculation.
*   [ ] Machine Learning pipeline (ARIMA/LSTM) for price prediction.
*   [ ] Sentiment analysis engine for crypto news feeds.

### Phase 3: Execution
*   [ ] Paper trading engine integration (Alpaca/CCXT).
*   [ ] Reinforcement Learning (RL) agent environment.
*   [ ] Automated strategy backtesting implementation.

---

## ⚠️ Disclaimer
**Educational Use Only.** This software is for research purposes. Cryptocurrency trading involves significant risk. The authors are not responsible for financial losses incurred through the use of this software.
