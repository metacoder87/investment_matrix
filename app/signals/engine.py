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

from app.models.instrument import Price
from app.analysis import add_technical_indicators
from app.connectors.sentiment import Sentiment
from app.connectors.coinmarketcap import CoinMarketCapConnector
from app.connectors.fundamental import CoinGeckoConnector
from app.connectors.coinpaprika import CoinPaprikaConnector
from app.connectors.financialmodelingprep import FinancialModelingPrepConnector


logger = logging.getLogger("cryptoinsight.signals")


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

    def generate_signal(self, symbol: str, lookback: int = 500) -> Optional[Signal]:
        """
        Generate a comprehensive signal for the given symbol using 50+ indicators.
        """
        symbol = symbol.strip().upper().replace("/", "-")
        
        # Fetch historical data
        prices = (
            self.db.query(Price)
            .filter(Price.symbol == symbol)
            .order_by(Price.timestamp.desc())
            .limit(lookback)
            .all()
        )

        if len(prices) < 50:
            logger.warning(f"Insufficient data for {symbol}: {len(prices)} rows")
            return None

        # Convert to DataFrame
        df = pd.DataFrame([{
            "timestamp": p.timestamp,
            "open": float(p.open or 0),
            "high": float(p.high or 0),
            "low": float(p.low or 0),
            "close": float(p.close or 0),
            "volume": float(p.volume or 0),
        } for p in reversed(prices)])

        df = df.sort_values("timestamp").reset_index(drop=True)

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

        # SuperTrend
        st = latest.get("SUPERT_7_3.0") # pandas-ta default name might change, robust check needed
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
             for i in range(len(buy_signals)): buy_signals[i] *= 1.2
             for i in range(len(sell_signals)): sell_signals[i] *= 1.2
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
        
        # Sentiment Analysis
        try:
            # Use base symbol for sentiment lookups (e.g. BTC from BTC-USD)
            base_sym = symbol.split("-")[0] if "-" in symbol else symbol
            sent_data = self.sentiment_connector.get_sentiment(base_sym)
            
            # Fear & Greed (Global Market Sentiment)
            fng = sent_data.get("fear_and_greed")
            if fng:
                fng_val = fng.get("value", 50)
                if fng_val <= 20: # Extreme Fear -> Potential Buy (Contrarian)
                     buy_signals.append(0.1)
                     reasons.append(f"Extreme Fear in Market ({fng_val})")
                elif fng_val >= 80: # Extreme Greed -> Potential Sell (Contrarian)
                     sell_signals.append(0.1)
                     reasons.append(f"Extreme Greed in Market ({fng_val})")
            
            # Token Sentiment (Stockgeist / LunarCrush via Sentiment wrapper)
            # Simplified logic: check if purely positive or negative signal exists in returned dicts
            # (Real implementation would parse specific scores from specific providers)
            
        except Exception as e:
            logger.warning(f"Sentiment analysis failed: {e}")

        # Fundamental Analysis
        try:
            # Try CMC first
            cmc = CoinMarketCapConnector()
            base_sym = symbol.split("-")[0] if "-" in symbol else symbol
            fund = cmc.get_fundamentals(base_sym)
            
            if not fund or fund.get("status") == "error":
                 # Fallback to CG
                 cg = CoinGeckoConnector()
                 # Try resolving ID for CG
                 cg_id = cg.get_coin_id_by_symbol(base_sym)
                 if cg_id:
                     fund = cg.get_coin_fundamentals(cg_id)
            
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
             # Coinpaprika Events
             cp = CoinPaprikaConnector()
             # Try to map symbol to ID broadly
             cp_id = symbol.lower()
             if "btc" in cp_id: cp_id = "btc-bitcoin"
             elif "eth" in cp_id: cp_id = "eth-ethereum"
             
             if "-" in cp_id:
                 events_res = cp.get_news(cp_id)
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
                             except: pass

             # FMP Simple Headline Scrape
             fmp = FinancialModelingPrepConnector()
             fmp_news = fmp.get_crypto_news(symbol.split("-")[0])
             if isinstance(fmp_news, list) and fmp_news:
                  bullish_kw = ["soar", "surge", "jump", "record", "bull"]
                  bearish_kw = ["crash", "plunge", "drop", "bear", "ban"]
                  
                  sentiment_score = 0
                  for article in fmp_news[:5]:
                      title = article.get("title", "").lower()
                      if any(k in title for k in bullish_kw): sentiment_score += 1
                      if any(k in title for k in bearish_kw): sentiment_score -= 1
                  
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
            if "BUY" in signal_type.value:
                stop_loss = current_price - (2.0 * atr)
                target_price = current_price + (4.0 * atr) # 2:1 Reward ratio
            elif "SELL" in signal_type.value:
                stop_loss = current_price + (2.0 * atr)
                target_price = current_price - (4.0 * atr)

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
                 except:
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
            target_price=round(target_price, 2) if target_price else None,
            stop_loss=round(stop_loss, 2) if stop_loss else None,
        )

    def generate_signals_batch(self, symbols: List[str]) -> List[Signal]:
        """Generate signals for multiple symbols."""
        signals = []
        for symbol in symbols:
            try:
                signal = self.generate_signal(symbol)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Failed to generate signal for {symbol}: {e}")
        return signals
