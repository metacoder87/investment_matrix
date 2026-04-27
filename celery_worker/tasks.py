from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import ccxt.async_support as ccxt
from sqlalchemy import func

import app.models.portfolio  # noqa: F401
from app.connectors.fundamental import CoinGeckoConnector
from app.models.instrument import Coin, Price
from app.models.paper import PaperAccount, PaperSchedule
from app.models.research import AgentGuardrailProfile
from app.models.user import User
from celery_app import celery_app
from database import session_scope
from app.services.asset_status import classify_asset, update_asset_status
from app.services.imports.download import (
    binance_vision_daily_url,
    build_download_spec,
    date_range,
    download_file,
    dukascopy_hourly_url,
)
from app.services.imports.ingest import ingest_ticks
from app.services.imports.registry import get_importer
from app.services.paper_trading import PaperStepPayload, execute_paper_step
from app.services.market_resolution import (
    ResolvedMarket,
    is_unsupported_market_error,
    resolve_supported_market,
)

logger = logging.getLogger("cryptoinsight.tasks")


async def _close_exchange_client(exchange) -> None:
    try:
        await exchange.close()
        await asyncio.sleep(0)
    except Exception as exc:  # pragma: no cover - defensive cleanup for CCXT/aiohttp
        logger.warning("Failed to close CCXT exchange client cleanly: %s", exc)


class UnsupportedMarketError(ValueError):
    pass


def _normalize_symbol(symbol: str, exchange_id: str) -> str:
    """Normalize symbol format for different exchanges."""
    symbol = symbol.strip().upper()
    # Strip exchange prefix if present (e.g. COINBASE:BTC-USD -> BTC-USD)
    if ":" in symbol:
        _, symbol = symbol.split(":", 1)
    # Convert dash format to slash for CCXT
    if "-" in symbol and "/" not in symbol:
        base, quote = symbol.split("-", 1)
        symbol = f"{base}/{quote}"
    # Binance uses USDT instead of USD
    if exchange_id == "binance" and symbol.endswith("/USD"):
        symbol = symbol[:-3] + "USDT"
    return symbol




def _normalize_symbol_db(symbol: str, exchange_id: str) -> str:
    symbol_ccxt = _normalize_symbol(symbol, exchange_id)
    return symbol_ccxt.replace("/", "-").upper()


def _normalize_dukascopy_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if "/" in raw or "-" in raw:
        return raw.replace("/", "-")
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH", "EUR"):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            return f"{base}-{quote}"
    return raw


def _parse_coingecko_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@celery_app.task
def ingest_historical_data(
    symbol: str,
    timeframe: str = "1m",
    limit: int = 100,
    exchange_id: str = "coinbase",
):
    """
    Ingests historical price data for a given symbol (basic version).
    """
    exchange_key = exchange_id.strip().lower()
    symbol_ccxt = _normalize_symbol(symbol, exchange_key)
    symbol_db = _normalize_symbol_db(symbol, exchange_key)
    
    async def fetch():
        exchange_cls = getattr(ccxt, exchange_key, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown exchange_id={exchange_id!r} (must be a CCXT exchange id)")
        exchange = exchange_cls({"enableRateLimit": True})
        try:
            timeframe_seconds = exchange.parse_timeframe(timeframe)
            since = exchange.milliseconds() - limit * timeframe_seconds * 1000
            return await exchange.fetch_ohlcv(
                symbol_ccxt,
                timeframe=timeframe,
                since=since,
                limit=limit,
            )
        finally:
            await _close_exchange_client(exchange)

    ohlcv = asyncio.run(fetch())

    with session_scope() as db:
        for row in ohlcv:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            price = Price(
                symbol=symbol_db,
                exchange=exchange_key,
                timestamp=ts,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            db.add(price)
    return f"Successfully ingested {len(ohlcv)} data points for {symbol_db}"


@celery_app.task(bind=True, soft_time_limit=300, time_limit=360, max_retries=0)
def backfill_historical_candles(
    self,
    symbol: str,
    exchange_id: str = "coinbase",
    timeframe: str = "1m",
    days: int = 7,
    start_from: Optional[str] = None,
):
    """
    Backfill historical OHLCV candles for a symbol.
    
    Fetches data in chunks to handle rate limits and large date ranges.
    Uses upsert logic to avoid duplicates.
    
    Args:
        symbol: Trading pair (e.g., "BTC-USD" or "BTC/USDT")
        exchange_id: CCXT exchange ID (default: binance)
        timeframe: Candle timeframe (default: 1m)
        days: Number of days to backfill (default: 7)
        start_from: Optional ISO timestamp to start from (for resuming)
    """
    requested_exchange = exchange_id.strip().lower()
    resolved: ResolvedMarket | None = None
    if requested_exchange == "auto":
        resolved = asyncio.run(resolve_supported_market(symbol, requested_exchange))
        if resolved is None:
            symbol_db = symbol.strip().upper().replace("/", "-")
            with session_scope() as db:
                update_asset_status(
                    db,
                    exchange="auto",
                    symbol=symbol_db,
                    status="unsupported",
                    is_supported=False,
                    is_analyzable=False,
                    task_id=getattr(self.request, "id", None),
                    failure_reason="No configured exchange exposes a supported spot market for this symbol.",
                )
            return {"status": "unsupported", "symbol": symbol_db, "exchange": "auto", "fetched": 0}
        exchange_key = resolved.exchange
        symbol_ccxt = resolved.ccxt_symbol
        symbol_db = resolved.db_symbol
    else:
        exchange_key = requested_exchange
        symbol_ccxt = _normalize_symbol(symbol, exchange_key)
        symbol_db = _normalize_symbol_db(symbol, exchange_key)

    with session_scope() as db:
        update_asset_status(
            db,
            exchange=exchange_key,
            symbol=symbol_db,
            status="backfill_pending",
            is_supported=True,
            is_analyzable=True,
            task_id=getattr(self.request, "id", None),
        )
    
    async def fetch_all():
        exchange_cls = getattr(ccxt, exchange_key, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown exchange_id={exchange_id!r}")
        
        exchange = exchange_cls({"enableRateLimit": True})
        all_candles = []
        
        try:
            markets = await exchange.load_markets()
            if symbol_ccxt not in markets:
                raise UnsupportedMarketError(f"{exchange_key} does not have market symbol {symbol_ccxt}")

            timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
            
            # Calculate time range
            end_time = exchange.milliseconds()
            if start_from:
                start_time = int(datetime.fromisoformat(start_from.replace("Z", "+00:00")).timestamp() * 1000)
            else:
                start_time = end_time - (days * 24 * 60 * 60 * 1000)
            
            # Fetch in chunks (most exchanges limit to 1000 candles per request)
            chunk_size = 1000
            current_since = start_time
            total_fetched = 0
            
            consecutive_errors = 0
            while current_since < end_time:
                try:
                    candles = await exchange.fetch_ohlcv(
                        symbol_ccxt,
                        timeframe=timeframe,
                        since=current_since,
                        limit=chunk_size,
                    )
                    
                    if not candles:
                        break
                    
                    all_candles.extend(candles)
                    total_fetched += len(candles)
                    
                    # Move to next chunk
                    last_ts = candles[-1][0]
                    current_since = last_ts + timeframe_ms
                    
                    # Update task progress
                    progress = min(100, int((current_since - start_time) / (end_time - start_time) * 100))
                    self.update_state(state="PROGRESS", meta={"progress": progress, "fetched": total_fetched})
                    
                    # Rate limit protection
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    if isinstance(e, UnsupportedMarketError) or is_unsupported_market_error(e):
                        raise UnsupportedMarketError(str(e)) from e
                    if "429" in str(e) or "too many requests" in str(e).lower():
                        raise RuntimeError(f"Rate limited during backfill: {e}") from e
                    consecutive_errors += 1
                    logger.warning(f"Chunk fetch error at {current_since}: {e}")
                    if consecutive_errors >= 3:
                        raise RuntimeError(
                            f"Aborting backfill after {consecutive_errors} consecutive chunk failures at {current_since}: {e}"
                        ) from e
                    await asyncio.sleep(1)
                    continue
            
            return all_candles
            
        finally:
            await _close_exchange_client(exchange)
    
    logger.info(f"Starting backfill for {symbol_ccxt} on {exchange_key} ({days} days, {timeframe})")
    try:
        candles = asyncio.run(fetch_all())
    except UnsupportedMarketError as exc:
        with session_scope() as db:
            update_asset_status(
                db,
                exchange=exchange_key,
                symbol=symbol_db,
                status="unsupported",
                is_supported=False,
                is_analyzable=False,
                task_id=getattr(self.request, "id", None),
                failure_reason=str(exc),
            )
        logger.info("Backfill unsupported market: %s %s (%s)", exchange_key, symbol_db, exc)
        return {
            "status": "unsupported",
            "symbol": symbol_db,
            "exchange": exchange_key,
            "fetched": 0,
            "error": str(exc),
        }
    except Exception as exc:
        with session_scope() as db:
            update_asset_status(
                db,
                exchange=exchange_key,
                symbol=symbol_db,
                status="backfill_failed",
                is_supported=True,
                task_id=getattr(self.request, "id", None),
                failure_reason=str(exc),
            )
        logger.warning("Backfill failed for %s %s: %s", exchange_key, symbol_db, exc)
        return {
            "status": "backfill_failed",
            "symbol": symbol_db,
            "exchange": exchange_key,
            "fetched": 0,
            "error": str(exc),
        }
    
    if not candles:
        with session_scope() as db:
            update_asset_status(
                db,
                exchange=exchange_key,
                symbol=symbol_db,
                status="backfill_failed",
                row_count=0,
                task_id=getattr(self.request, "id", None),
                failure_reason="Exchange returned no candles.",
            )
        return {"status": "no_data", "symbol": symbol_db, "exchange": exchange_key, "fetched": 0}
    
    # Store in database with upsert logic
    inserted = 0
    skipped = 0
    
    latest_ts = None
    with session_scope() as db:
        for row in candles:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            latest_ts = ts if latest_ts is None or ts > latest_ts else latest_ts
            
            # Check for existing record
            existing = db.query(Price).filter(
                Price.exchange == exchange_key,
                Price.symbol == symbol_db,
                Price.timestamp == ts
            ).first()
            
            if existing:
                skipped += 1
                continue
            
            price = Price(
                symbol=symbol_db,
                exchange=exchange_key,
                timestamp=ts,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            db.add(price)
            inserted += 1

        total_rows = db.query(Price).filter(
            Price.exchange == exchange_key,
            Price.symbol == symbol_db,
        ).count()
        latest_ts = db.query(func.max(Price.timestamp)).filter(
            Price.exchange == exchange_key,
            Price.symbol == symbol_db,
        ).scalar()
        update_asset_status(
            db,
            exchange=exchange_key,
            symbol=symbol_db,
            status="ready" if total_rows >= 50 else "warming_up",
            is_supported=True,
            is_analyzable=True,
            row_count=total_rows,
            latest_candle_at=latest_ts,
            task_id=getattr(self.request, "id", None),
        )
    
    result = {
        "status": "success",
        "symbol": symbol_db,
        "exchange": exchange_key,
        "timeframe": timeframe,
        "days": days,
        "total_fetched": len(candles),
        "inserted": inserted,
        "skipped": skipped,
    }
    logger.info(f"Backfill complete: {result}")
    return result


@celery_app.task
def backfill_core_universe(
    exchange_id: str = "auto",
    symbols: Optional[list] = None,
    days: int = 7,
):
    """
    Backfill historical data for the core universe of trading pairs.
    
    Dynamic: Automatically selects the Top N coins by market cap from the DB.
    """
    from app.config import settings

    if symbols is None:
        with session_scope() as db:
            top_coins = (
                db.query(Coin.symbol)
                .order_by(Coin.market_cap_rank.asc())
                .limit(settings.TRACK_TOP_N_COINS)
                .all()
            )
            if top_coins:
                symbols = [f"{c.symbol.strip().upper()}-USD" for c in top_coins]
            else:
                symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"]
    
    logger.info(f"Triggering core backfill for {len(symbols)} symbols")
    
    results = []
    exchange_key = (exchange_id or "auto").strip().lower()
    for symbol in symbols:
        try:
            classification = classify_asset(symbol)
            if not classification.is_analyzable:
                with session_scope() as db:
                    update_asset_status(
                        db,
                        exchange=exchange_key,
                        symbol=symbol,
                        status=classification.status,
                        is_supported=False,
                        is_analyzable=False,
                        failure_reason=classification.reason,
                    )
                results.append({"symbol": symbol, "status": classification.status, "reason": classification.reason})
                continue

            task_symbol = symbol
            task_exchange = exchange_key
            if exchange_key == "auto":
                resolved = asyncio.run(resolve_supported_market(symbol, "auto"))
                if resolved is None:
                    with session_scope() as db:
                        update_asset_status(
                            db,
                            exchange="auto",
                            symbol=symbol,
                            status="unsupported",
                            is_supported=False,
                            is_analyzable=False,
                            failure_reason="No configured exchange exposes a supported spot market for this symbol.",
                        )
                    results.append({"symbol": symbol, "status": "unsupported"})
                    continue
                task_symbol = resolved.db_symbol
                task_exchange = resolved.exchange

            result = backfill_historical_candles.delay(
                symbol=task_symbol,
                exchange_id=task_exchange,
                days=days,
            )
            results.append({"symbol": task_symbol, "exchange": task_exchange, "task_id": result.id})
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})
    
    queued = [item for item in results if item.get("task_id")]
    return {"status": "queued", "count": len(queued), "tasks_sample": results[:5]}


@celery_app.task
def detect_and_fill_gaps(
    symbol: str,
    exchange_id: str = "coinbase",
    timeframe: str = "1m",
    max_gap_minutes: int = 60,
):
    """
    Detect gaps in stored price data and backfill them.
    """
    exchange_key = exchange_id.strip().lower()
    symbol_db = _normalize_symbol_db(symbol, exchange_key)
    timeframe_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(timeframe, 1)
    
    gaps_found = []
    
    with session_scope() as db:
        # Get all timestamps for this symbol, ordered
        prices = db.query(Price.timestamp).filter(
            Price.exchange == exchange_key,
            Price.symbol == symbol_db
        ).order_by(Price.timestamp.asc()).all()
        
        if len(prices) < 2:
            return {"status": "insufficient_data", "symbol": symbol_db}
        
        # Find gaps
        prev_ts = prices[0][0]
        for (current_ts,) in prices[1:]:
            expected_next = prev_ts + timedelta(minutes=timeframe_minutes)
            gap_minutes = (current_ts - expected_next).total_seconds() / 60
            
            if gap_minutes > max_gap_minutes:
                gaps_found.append({
                    "start": prev_ts.isoformat(),
                    "end": current_ts.isoformat(),
                    "gap_minutes": int(gap_minutes),
                })
            
            prev_ts = current_ts
    
    # Queue backfills for gaps
    for gap in gaps_found[:10]:  # Limit to 10 gaps per run
        backfill_historical_candles.delay(
            symbol=symbol,
            exchange_id=exchange_id,
            timeframe=timeframe,
            days=1,  # Small window
            start_from=gap["start"],
        )
    
    return {
        "status": "gaps_detected",
        "symbol": symbol_db,
        "gaps_found": len(gaps_found),
        "gaps_queued": min(10, len(gaps_found)),
        "gaps": gaps_found[:10],
    }


@celery_app.task
def fetch_and_store_coin_list():
    """
    Fetches and stores the list of all coins from CoinGecko.
    """
    cg = CoinGeckoConnector()
    all_coins = []
    per_page = 250
    # CoinGecko `coins/markets` is capped per page; paginate until empty.
    for page in range(1, 51):
        batch = cg.get_all_coins(per_page=per_page, page=page)
        if not batch:
            break
        all_coins.extend(batch)
        # If we received fewer items than requested, we've reached the end (or are using steady fallback)
        if len(batch) < per_page:
            break

    with session_scope() as db:
        for coin_data in all_coins:
            coin = Coin(
                id=coin_data.get("id"),
                symbol=coin_data.get("symbol"),
                name=coin_data.get("name"),
                market_cap_rank=coin_data.get("market_cap_rank"),
                market_cap=coin_data.get("market_cap"),
                current_price=coin_data.get("current_price"),
                price_change_percentage_24h=coin_data.get("price_change_percentage_24h"),
                image=coin_data.get("image"),
                last_updated=_parse_coingecko_timestamp(coin_data.get("last_updated")),
            )
            db.merge(coin)

    return f"Successfully ingested {len(all_coins)} coins."


@celery_app.task
def fetch_and_store_news(query: str = 'crypto'):
    """
    Fetches and stores news for a given query.
    """
    from app.connectors.news import News
    
    logger.info(f"Starting news ingestion for query: {query}")
    
    try:
        news_connector = News()
        results = news_connector.get_news(query)
        
        # Summary of results
        summary = {source: len(articles) if articles else 0 for source, articles in results.items()}
        logger.info(f"News ingestion complete. Results: {summary}")
        
        # NOTE: Since no 'News' table exists in DB, we currently just log the availability.
        # This confirms API keys are working and connectors are active.
        # Future improvement: Save 'results' to Redis or a new 'News' table.
        
        return f"News ingestion successful: {summary}"
    except Exception as e:
        logger.error(f"News ingestion failed: {e}")
        return f"News ingestion failed: {e}"


@celery_app.task(bind=True)
def import_binance_vision_range(
    self,
    symbol: str,
    exchange: str = "binance",
    kind: str = "trades",
    start_date: str | None = None,
    end_date: str | None = None,
    owner_id: str | None = None,
):
    """
    Import Binance Vision trades/aggTrades for a date range (daily ZIPs).
    """
    kind = kind.strip()
    if kind.lower() in {"agg_trades", "aggtrades"}:
        kind = "aggTrades"
    start = date.fromisoformat(start_date) if start_date else date.today()
    end = date.fromisoformat(end_date) if end_date else start
    days = date_range(start, end)

    imported = 0
    total_days = max(1, len(days))
    registry_kind = "agg_trades" if kind == "aggTrades" else "trades"
    for idx, day in enumerate(days):
        url = binance_vision_daily_url(symbol, day, kind)
        filename = f"{symbol.replace('-', '').upper()}-{kind}-{day.isoformat()}.zip"
        spec = build_download_spec(url, filename)
        try:
            path = download_file(spec)
            importer = get_importer(f"binance_vision_{registry_kind}", path=path, symbol=symbol, exchange=exchange)
            with session_scope() as db:
                imported += ingest_ticks(
                    db,
                    importer=importer,
                    source="binance_vision",
                    kind=kind,
                    source_key=spec.source_key,
                    owner_id=owner_id,
                    ingest_source="binance_vision",
                )
        except FileNotFoundError:
            logger.warning("Binance Vision file not found: %s", url)
        except Exception as exc:
            logger.exception("Binance Vision import failed: %s", exc)
            raise

        progress = int(((idx + 1) / total_days) * 100)
        self.update_state(state="PROGRESS", meta={"progress": progress, "days": len(days)})

    return {"status": "success", "imported": imported, "days": len(days)}


@celery_app.task
def import_binance_vision_yesterday(
    symbol: str,
    exchange: str = "binance",
    kind: str = "trades",
    owner_id: str | None = None,
):
    day = (date.today() - timedelta(days=1)).isoformat()
    return import_binance_vision_range(
        symbol=symbol,
        exchange=exchange,
        kind=kind,
        start_date=day,
        end_date=day,
        owner_id=owner_id,
    )


@celery_app.task(bind=True)
def import_dukascopy_range(
    self,
    symbol: str,
    exchange: str = "dukascopy",
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    owner_id: str | None = None,
    price_scale: int = 100_000,
    volume_scale: int = 100_000,
):
    """
    Import Dukascopy BI5 hourly ticks for a datetime range.
    """
    if start_datetime is None or end_datetime is None:
        raise ValueError("start_datetime and end_datetime are required (ISO 8601)")
    start = datetime.fromisoformat(start_datetime.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_datetime.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start > end:
        raise ValueError("start_datetime must be <= end_datetime")

    symbol = _normalize_dukascopy_symbol(symbol)
    if "-" not in symbol:
        raise ValueError("symbol must be BASE-QUOTE (e.g. BTC-USD) or include a known quote suffix")

    imported = 0
    total_hours = int(((end - start).total_seconds() // 3600) + 1)
    current = start
    processed = 0

    while current <= end:
        url = dukascopy_hourly_url(symbol, current)
        filename = f"{symbol.upper()}_{current:%Y%m%d_%H}h_ticks.bi5"
        spec = build_download_spec(url, filename)
        try:
            path = download_file(spec)
            importer = get_importer(
                "dukascopy_bi5",
                path=path,
                symbol=symbol,
                exchange=exchange,
                base_time=current,
                price_scale=price_scale,
                volume_scale=volume_scale,
            )

            with session_scope() as db:
                imported += ingest_ticks(
                    db,
                    importer=importer,
                    source="dukascopy",
                    kind="bi5",
                    source_key=spec.source_key,
                    owner_id=owner_id,
                    ingest_source="dukascopy",
                )
        except FileNotFoundError:
            logger.warning("Dukascopy file not found: %s", url)
        except Exception as exc:
            logger.exception("Dukascopy import failed: %s", exc)
            raise

        processed += 1
        progress = int((processed / max(1, total_hours)) * 100)
        self.update_state(state="PROGRESS", meta={"progress": progress, "hours": total_hours})
        current += timedelta(hours=1)

    return {"status": "success", "imported": imported, "hours": total_hours}


def _schedule_due(schedule: PaperSchedule, now: datetime) -> bool:
    if schedule.last_run_at is None:
        return True
    elapsed = (now - schedule.last_run_at).total_seconds()
    return elapsed >= max(1, schedule.interval_seconds or 0)


def _apply_drawdown_guardrail(account: PaperAccount, schedule: PaperSchedule) -> bool:
    if schedule.max_drawdown_pct is None:
        return False
    if not account.equity_peak or not account.last_equity:
        return False
    if account.equity_peak <= 0:
        return False
    drawdown_pct = (1 - (account.last_equity / account.equity_peak)) * 100
    if drawdown_pct >= schedule.max_drawdown_pct:
        schedule.is_active = False
        schedule.disabled_reason = f"max_drawdown {drawdown_pct:.2f}%"
        return True
    return False


@celery_app.task
def tick_paper_schedules():
    now = datetime.now(timezone.utc)
    ran = 0
    skipped = 0

    with session_scope() as db:
        schedules = (
            db.query(PaperSchedule)
            .filter(PaperSchedule.is_active.is_(True))
            .all()
        )

        for schedule in schedules:
            if not _schedule_due(schedule, now):
                skipped += 1
                continue

            account = (
                db.query(PaperAccount)
                .filter(PaperAccount.id == schedule.account_id)
                .first()
            )
            if not account:
                schedule.is_active = False
                schedule.disabled_reason = "missing_account"
                continue

            result = execute_paper_step(
                db=db,
                account=account,
                payload=PaperStepPayload(
                    symbol=schedule.symbol,
                    exchange=schedule.exchange,
                    timeframe=schedule.timeframe,
                    lookback=schedule.lookback,
                    as_of=None,
                    source=schedule.source,
                    strategy=schedule.strategy,
                    strategy_params=schedule.strategy_params or {},
                ),
                commit=False,
            )

            if result.get("status") == "no_data":
                skipped += 1
                continue

            schedule.last_run_at = now
            _apply_drawdown_guardrail(account, schedule)
            ran += 1

    return {"status": "ok", "ran": ran, "skipped": skipped}


@celery_app.task
def run_crew_research_cycles():
    from app.config import settings
    from app.services.crew_autonomy import run_autonomous_research_cycle

    if not settings.CREW_RESEARCH_ENABLED:
        return {"status": "disabled", "reason": "CREW_RESEARCH_ENABLED is false."}

    results = []
    with session_scope() as db:
        profiles = (
            db.query(AgentGuardrailProfile)
            .filter(AgentGuardrailProfile.research_enabled.is_(True))
            .all()
        )
        for profile in profiles:
            user = db.query(User).filter(User.id == profile.user_id).first()
            if not user:
                continue
            try:
                result = run_autonomous_research_cycle(db, user)
                results.append({"user_id": user.id, **result})
            except Exception as exc:
                logger.exception("Autonomous research cycle failed for user_id=%s", user.id)
                results.append({"user_id": user.id, "status": "failed", "error": str(exc)})
    return {"status": "ok", "users": len(results), "results": results}


@celery_app.task
def run_crew_research_cycle_for_user(user_id: int):
    from app.config import settings
    from app.services.crew_autonomy import run_autonomous_research_cycle

    if not settings.CREW_RESEARCH_ENABLED:
        return {"status": "disabled", "reason": "CREW_RESEARCH_ENABLED is false.", "user_id": user_id}

    with session_scope() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"status": "not_found", "reason": "User not found.", "user_id": user_id}
        try:
            return {"user_id": user.id, **run_autonomous_research_cycle(db, user)}
        except Exception as exc:
            logger.exception("Immediate autonomous research cycle failed for user_id=%s", user_id)
            return {"status": "failed", "user_id": user_id, "error": str(exc)}


@celery_app.task
def monitor_crew_triggers():
    from app.config import settings
    from app.services.crew_autonomy import monitor_price_triggers

    if not settings.CREW_TRIGGER_MONITOR_ENABLED:
        return {"status": "disabled", "reason": "CREW_TRIGGER_MONITOR_ENABLED is false."}

    results = []
    with session_scope() as db:
        profiles = (
            db.query(AgentGuardrailProfile)
            .filter(AgentGuardrailProfile.trigger_monitor_enabled.is_(True))
            .all()
        )
        for profile in profiles:
            user = db.query(User).filter(User.id == profile.user_id).first()
            if not user:
                continue
            try:
                result = monitor_price_triggers(db, user)
                results.append({"user_id": user.id, **result})
            except Exception as exc:
                logger.exception("Crew trigger monitor failed for user_id=%s", user.id)
                results.append({"user_id": user.id, "status": "failed", "error": str(exc)})
    return {"status": "ok", "users": len(results), "results": results}


@celery_app.task
def sync_exchange_markets_task(exchange_id: str = "kraken"):
    from app.services.exchange_markets import sync_exchange_markets

    exchange_key = (exchange_id or "kraken").strip().lower()
    with session_scope() as db:
        return asyncio.run(sync_exchange_markets(db, exchange=exchange_key))


@celery_app.task
def backfill_kraken_supported_markets(limit: int | None = None, days: int = 7):
    from app.config import settings
    from app.services.exchange_markets import queue_kraken_backfills

    with session_scope() as db:
        return queue_kraken_backfills(
            db,
            limit=int(limit or settings.MARKET_UNIVERSE_TARGET),
            days=days,
        )










