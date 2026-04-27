"""
Signal generation engine for CryptoInsight.

Combines technical indicators, price action, and optional ML predictions
to generate actionable buy/sell signals with confidence scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List
import logging

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.instrument import Price
from app.config import settings
from app.analysis import add_technical_indicators
from app.connectors.sentiment import Sentiment
from app.connectors.coinmarketcap import CoinMarketCapConnector
from app.connectors.fundamental import CoinGeckoConnector
from app.connectors.coinpaprika import CoinPaprikaConnector
from app.connectors.financialmodelingprep import FinancialModelingPrepConnector


logger = logging.getLogger("cryptoinsight.signals")


def _normalize_symbol_for_exchange(exchange: str, symbol: str) -> str:
    exchange = (exchange or "").strip().lower()
    symbol = symbol.strip().upper().replace("/", "-")
    if exchange == "binance" and symbol.endswith("-USD"):
        return f"{symbol[:-4]}-USDT"
    if exchange == "coinbase" and "-" not in symbol:
        return f"{symbol}-USD"
    return symbol


class SignalType(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class Signal:
    """A trading signal with reasoning."""
    symbol: str
    signal_type: SignalType
    confidence: float  # 0.0 to 1.0
    price: float
    timestamp: datetime
    reasons: List[str]
    indicators: dict
    risk_reward: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "signal": self.signal_type.value,
            "confidence": round(self.confidence, 2),
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "reasons": self.reasons,
            "indicators": self.indicators,
            "risk_reward": self.risk_reward,
            "target_price": self.target_price,
            "stop_loss": self.stop_loss,
        }


class SignalEngine:
    """
    Generates trading signals based on technical analysis.
    
    Strategies:
    1. RSI oversold/overbought
    2. MACD crossovers
    3. Bollinger Band breakouts
    4. Price/SMA crossovers
    5. Volume confirmation
    """

    def __init__(
        self, 
        db: Session,
        sentiment_connector: Optional[Sentiment] = None,
        cmc_connector: Optional[CoinMarketCapConnector] = None,
        cg_connector: Optional[CoinGeckoConnector] = None,
        cp_connector: Optional[CoinPaprikaConnector] = None,
        fmp_connector: Optional[FinancialModelingPrepConnector] = None
    ):
        self.db = db
        self.sentiment_connector = sentiment_connector or Sentiment()
        self.cmc_connector = cmc_connector or CoinMarketCapConnector()
        self.cg_connector = cg_connector or CoinGeckoConnector()
        self.cp_connector = cp_connector or CoinPaprikaConnector()
        self.fmp_connector = fmp_connector or FinancialModelingPrepConnector()

    def generate_signal(self, symbol: str, lookback: int = 500, exchange: str | None = None, prefetched_df: pd.DataFrame | None = None, include_externals: bool = True) -> Optional[Signal]:
        """
        Generate a comprehensive signal for the given symbol.
        Args:
            prefetched_df: Optional DataFrame with 'timestamp', 'open', 'high', 'low', 'close', 'volume' columns.
                           If provided, DB query is skipped.
        """
        symbol = symbol.strip().upper().replace("/", "-")
        exchange_key = (exchange or "").strip().lower()
        if not exchange_key:
            exchange_key = (settings.STREAM_EXCHANGE or "coinbase").strip().lower()
        symbol = _normalize_symbol_for_exchange(exchange_key, symbol)
        
        if prefetched_df is None:
            # Fetch historical data
            prices = (
                self.db.query(Price)
                .filter(Price.exchange == exchange_key, Price.symbol == symbol)
                .order_by(Price.timestamp.desc())
                .limit(lookback)
                .all()
            )

            if len(prices) < 50:
                logger.warning(f"Insufficient data for {symbol}: {len(prices)} rows")
                return None

            # Convert to DataFrame
            prefetched_df = pd.DataFrame([{
                "timestamp": p.timestamp,
                "open": float(p.open or 0),
                "high": float(p.high or 0),
                "low": float(p.low or 0),
                "close": float(p.close or 0),
                "volume": float(p.volume or 0),
            } for p in reversed(prices)])

        df = prefetched_df.sort_values("timestamp").reset_index(drop=True)
        if len(df) < 50:
             return None

        # Add technical indicators (Now uses pandas-ta strategy)
        df = add_technical_indicators(df)

        # Get latest values
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        # Collect signal components
        buy_signals = []
        sell_signals = []
        reasons = []
        
        current_price = latest["close"]
        
        # --- 1. MOMENTUM ---
        
        # RSI (14)
        rsi = latest.get("rsi")
        if pd.notna(rsi):
            if rsi <= 30:
                buy_signals.append(0.3)
                reasons.append(f"RSI oversold ({rsi:.1f})")
            elif rsi >= 70:
                sell_signals.append(0.3)
                reasons.append(f"RSI overbought ({rsi:.1f})")

        # Stochastic (14,3,3)
        stoch_k = latest.get("STOCHk_14_3_3")
        stoch_d = latest.get("STOCHd_14_3_3")
        if pd.notna(stoch_k) and pd.notna(stoch_d):
            if stoch_k < 20 and stoch_d < 20 and stoch_k > stoch_d:
                buy_signals.append(0.2)
                reasons.append("Stochastic bullish crossover in oversold zone")
            elif stoch_k > 80 and stoch_d > 80 and stoch_k < stoch_d:
                sell_signals.append(0.2)
                reasons.append("Stochastic bearish crossover in overbought zone")

        # TSI (True Strength Index)
        tsi = latest.get("TSI_13_25_13")
        if pd.notna(tsi):
            if tsi > 0 and prev.get("TSI_13_25_13", 0) <= 0:
                buy_signals.append(0.15)
                reasons.append("TSI bullish zero cross")
            elif tsi < 0 and prev.get("TSI_13_25_13", 0) >= 0:
                sell_signals.append(0.15)
                reasons.append("TSI bearish zero cross")

        # Awesome Oscillator (AO)
        ao = latest.get("AO_5_34")
        if pd.notna(ao):
            if ao > 0 and prev.get("AO_5_34", 0) <= 0:
                buy_signals.append(0.1)
                reasons.append("Awesome Oscillator flip to positive")
            elif ao < 0 and prev.get("AO_5_34", 0) >= 0:
                sell_signals.append(0.1)
                reasons.append("Awesome Oscillator flip to negative")

        # --- 2. TREND ---
        
        # EMA Trends
        ema_9 = latest.get("EMA_9")
        ema_21 = latest.get("EMA_21")
        ema_55 = latest.get("EMA_55")
        
        if pd.notna(ema_9) and pd.notna(ema_21) and pd.notna(ema_55):
            if ema_9 > ema_21 > ema_55:
                buy_signals.append(0.3)
                reasons.append("Strong bull trend (EMA 9>21>55)")
            elif ema_9 < ema_21 < ema_55:
                sell_signals.append(0.3)
                reasons.append("Strong bear trend (EMA 9<21<55)")

        # SuperTrend logic (if we wanted to use it)
        # st = latest.get("SUPERT_7_3.0") # pandas-ta default name might change
        # Often returns SUPERT_7_3.0, SUPERTd_7_3.0, SUPERTl_7_3.0, SUPERTs_7_3.0
        # We need the direction (1 or -1) usually in SUPERTd
        st_dir = latest.get("SUPERTd_10_3.0") 
        if pd.notna(st_dir):
            if st_dir == 1:
                buy_signals.append(0.15)
                reasons.append("SuperTrend Bullish")
            elif st_dir == -1:
                sell_signals.append(0.15)
                reasons.append("SuperTrend Bearish")

        # MACD
        macd_hist = latest.get("macdhist")
        if pd.notna(macd_hist) and macd_hist > 0:
             buy_signals.append(0.05)
        elif pd.notna(macd_hist) and macd_hist < 0:
             sell_signals.append(0.05)

        # ADX (Trend Strength)
        adx = latest.get("ADX_14")
        if pd.notna(adx) and adx > 25:
             # Strong trend existing, amplifies other signals
             for i in range(len(buy_signals)):
                 buy_signals[i] *= 1.2
             for i in range(len(sell_signals)):
                 sell_signals[i] *= 1.2
             reasons.append(f"Strong Trend (ADX {adx:.1f})")

        # --- 3. VOLATILITY ---
        
        # Bollinger Bands
        bb_upper = latest.get("bbands_upper")
        bb_lower = latest.get("bbands_lower")
        
        if pd.notna(bb_lower) and pd.notna(bb_upper):
            if current_price <= bb_lower:
                buy_signals.append(0.25)
                reasons.append("Price at BB Lower Support")
            elif current_price >= bb_upper:
                sell_signals.append(0.25)
                reasons.append("Price at BB Upper Resistance")

        # --- 4. VOLUME ---
        
        # Chaikin Money Flow
        cmf = latest.get("CMF_20")
        if pd.notna(cmf):
            if cmf > 0.2:
                 buy_signals.append(0.15)
                 reasons.append("Strong money inflow (CMF > 0.2)")
            elif cmf < -0.2:
                 sell_signals.append(0.15)
                 reasons.append("Strong money outflow (CMF < -0.2)")

        # --- 5. SENTIMENT & FUNDAMENTALS ---
        if include_externals:

            # Sentiment Analysis
            # DISABLED TEMPORARILY: Async/Sync conflict with batch processing
            # try:
            #     # Use base symbol for sentiment lookups (e.g. BTC from BTC-USD)
            #     base_sym = symbol.split("-")[0] if "-" in symbol else symbol
            #     # sent_data = self.sentiment_connector.get_sentiment(base_sym)
            #     
            #     # Fear & Greed (Global Market Sentiment)
            #     # fng = sent_data.get("fear_and_greed")
            #     # if fng:
            #     #     fng_val = fng.get("value", 50)
            #     #     if fng_val <= 20: # Extreme Fear -> Potential Buy (Contrarian)
            #     #          buy_signals.append(0.1)
            #     #          reasons.append(f"Extreme Fear in Market ({fng_val})")
            #     #     elif fng_val >= 80: # Extreme Greed -> Potential Sell (Contrarian)
            #     #          sell_signals.append(0.1)
            #     #          reasons.append(f"Extreme Greed in Market ({fng_val})")
            #     
            #     # Token Sentiment (Stockgeist / LunarCrush via Sentiment wrapper)
            #     # Simplified logic: check if purely positive or negative signal exists in returned dicts
            #     # (Real implementation would parse specific scores from specific providers)
            #     pass
            # except Exception as e:
            #     logger.warning(f"Sentiment analysis failed: {e}")

            # Fundamental Analysis
            try:
                base_sym = symbol.split("-")[0] if "-" in symbol else symbol
                fund = self.cmc_connector.get_fundamentals(base_sym)

                if not fund or fund.get("status") == "error":
                     # Fallback to CG
                     cg_id = self.cg_connector.get_coin_id_by_symbol(base_sym)
                     if cg_id:
                         fund = self.cg_connector.get_coin_fundamentals(cg_id)

                if fund and isinstance(fund, dict) and "market_cap" in fund:
                    mc = fund.get("market_cap")
                    fdv = fund.get("fully_diluted_valuation")

                    if mc and fdv and mc > 0:
                        fdv_mc_ratio = fdv / mc
                        if fdv_mc_ratio > 10.0:
                            sell_signals.append(0.15)
                            reasons.append(f"High Dilution Risk (FDV/MC: {fdv_mc_ratio:.1f}x)")
                        elif fdv_mc_ratio < 1.1:
                            buy_signals.append(0.05)
                            reasons.append("Low Dilution / High Circulating Supply")

            except Exception as e:
                logger.warning(f"Fundamental analysis failed: {e}")

            # Qualitative Analysis (Events/News)
            try:
                 # Try to map symbol to ID broadly
                 cp_id = symbol.lower()
                 if "btc" in cp_id:
                     cp_id = "btc-bitcoin"
                 elif "eth" in cp_id:
                     cp_id = "eth-ethereum"

                 if "-" in cp_id:
                     events_res = self.cp_connector.get_news(cp_id)
                     if events_res.get("status") == "ok":
                         events = events_res.get("events", [])
                         # Check for recent or upcoming high-impact events
                         today = datetime.now()
                         for evt in events[:3]: # check top 3
                             evt_date = evt.get("date")
                             if evt_date:
                                 # simple parsing, assuming YYYY-MM-DD
                                 try:
                                     ed = datetime.strptime(evt_date, "%Y-%m-%d")
                                     delta = (ed - today).days
                                     if -7 <= delta <= 30: # Recent or upcoming
                                         if "hard fork" in evt.get("name", "").lower():
                                             reasons.append(f"Hard Fork Event: {evt.get('name')}")
                                             # Volatility expected, neutral-bullish typically
                                         elif "launch" in evt.get("name", "").lower():
                                             buy_signals.append(0.1)
                                             reasons.append(f"Launch Event: {evt.get('name')}")
                                 except Exception:
                                     pass

                 # FMP Simple Headline Scrape
                 fmp_news = self.fmp_connector.get_crypto_news(symbol.split("-")[0])
                 if isinstance(fmp_news, list) and fmp_news:
                      bullish_kw = ["soar", "surge", "jump", "record", "bull"]
                      bearish_kw = ["crash", "plunge", "drop", "bear", "ban"]

                      sentiment_score = 0
                      for article in fmp_news[:5]:
                          title = article.get("title", "").lower()
                          if any(k in title for k in bullish_kw):
                              sentiment_score += 1
                          if any(k in title for k in bearish_kw):
                              sentiment_score -= 1

                      if sentiment_score >= 2:
                          buy_signals.append(0.1)
                          reasons.append("Bullish News Headlines")
                      elif sentiment_score <= -2:
                          sell_signals.append(0.1)
                          reasons.append("Bearish News Headlines")

            except Exception as e:
                 logger.warning(f"Qualitative analysis failed: {e}")

        # Calculate final signal
        buy_score = sum(buy_signals)
        sell_score = sum(sell_signals)
        
        # Normalize
        net_score = buy_score - sell_score
        # Max reasonable score is around 1.5-2.0, so divide by 1.5 for confidence
        confidence = min(1.0, abs(net_score) / 1.5) 
        
        if net_score >= 0.5:
            signal_type = SignalType.STRONG_BUY
        elif net_score >= 0.2:
            signal_type = SignalType.BUY
        elif net_score <= -0.5:
            signal_type = SignalType.STRONG_SELL
        elif net_score <= -0.2:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.HOLD
            confidence = max(0.1, 1.0 - confidence) # Confidence in holding

        # Calculate limits via ATR
        atr = latest.get("atr")
        target_price = None
        stop_loss = None
        
        if pd.notna(atr) and atr > 0:
            if signal_type in {SignalType.BUY, SignalType.STRONG_BUY}:
                stop_loss = current_price - max(2.0 * atr, current_price * 0.01)
                target_price = current_price + max(4.0 * atr, current_price * 0.02)  # 2:1 Reward ratio
            elif signal_type in {SignalType.SELL, SignalType.STRONG_SELL}:
                stop_loss = current_price + max(2.0 * atr, current_price * 0.01)
                target_price = current_price - max(4.0 * atr, current_price * 0.02)

        def _round_dynamic(val: float | None) -> float | None:
            if val is None:
                return None
            return round(val, 8) if current_price < 1.0 else round(val, 4)

        # Build indicators dict for frontend
        indicators = {}
        # Serialize specific interesting ones
        interest_keys = [
            "rsi", "macd", "macdsignal", "macdhist", 
            "bbands_upper", "bbands_lower", "sma_50", "sma_200", 
            "atr", "obv", "STOCHk_14_3_3", "STOCHd_14_3_3", 
            "ADX_14", "AO_5_34", "CMF_20", "SUPERTd_10_3.0"
        ]
        
        for k, v in latest.items():
            if isinstance(k, str) and (k in interest_keys or k.startswith("EMA_")):
                 try:
                     val = float(v)
                     if pd.notna(val):
                         indicators[k] = round(val, 4)
                 except Exception:
                     pass

        if not reasons:
            reasons.append("Neutral market conditions")

        return Signal(
            symbol=symbol,
            signal_type=signal_type,
            confidence=round(confidence, 2),
            price=current_price,
            timestamp=latest["timestamp"],
            reasons=reasons,
            indicators=indicators,
            risk_reward=2.0,
            target_price=_round_dynamic(target_price),
            stop_loss=_round_dynamic(stop_loss),
        )

    def generate_signals_batch(
        self,
        symbols: List[str],
        exchange_map: dict[str, str] | None = None,
        lookback: int = 100,
        include_externals: bool = True,
    ) -> List[Signal]:
        # Generate signals for multiple symbols efficiently using window functions.
        default_exchange = (settings.STREAM_EXCHANGE or "coinbase").strip().lower()
        exchange_map = exchange_map or {}

        buckets: dict[str, list[str]] = {}
        symbol_norm_map: dict[str, str] = {}
        for symbol in symbols:
            ex = (exchange_map.get(symbol) or default_exchange).strip().lower()
            if not ex:
                ex = default_exchange
            norm_symbol = _normalize_symbol_for_exchange(ex, symbol)
            symbol_norm_map[symbol] = norm_symbol
            buckets.setdefault(ex, []).append(norm_symbol)

        grouped: dict[str, list[dict]] = {}
        try:
            for ex, syms in buckets.items():
                if not syms:
                    continue
                subquery = (
                    self.db.query(
                        Price.symbol,
                        Price.timestamp,
                        Price.open,
                        Price.high,
                        Price.low,
                        Price.close,
                        Price.volume,
                        func.row_number().over(
                            partition_by=Price.symbol,
                            order_by=desc(Price.timestamp)
                        ).label("rn")
                    )
                    .filter(
                        Price.symbol.in_(syms),
                        Price.exchange == ex
                    )
                    .subquery()
                )

                rows = self.db.query(subquery).filter(subquery.c.rn <= lookback).all()

                for r in rows:
                    if r.symbol not in grouped:
                        grouped[r.symbol] = []
                    grouped[r.symbol].append({
                        "timestamp": r.timestamp,
                        "open": float(r.open or 0),
                        "high": float(r.high or 0),
                        "low": float(r.low or 0),
                        "close": float(r.close or 0),
                        "volume": float(r.volume or 0)
                    })
        except Exception as e:
            logger.error(f"Batch query failed: {e}")
            return []

        signals = []
        for symbol in symbols:
            try:
                norm_symbol = symbol_norm_map.get(symbol, symbol)
                data = grouped.get(norm_symbol, [])
                if not data:
                    continue

                df = pd.DataFrame(data)

                signal = self.generate_signal(
                    norm_symbol,
                    exchange=(exchange_map or {}).get(symbol),
                    lookback=lookback,
                    prefetched_df=df,
                    include_externals=include_externals,
                )

                if signal:
                    signals.append(signal)
            except Exception:
                pass # logger.debug(f"Failed to generate signal for {symbol}: {e}")

        return signals





