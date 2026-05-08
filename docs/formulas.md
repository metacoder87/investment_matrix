## Cryptocurrency day trading formulas ##

1. Position Sizing: The Kelly Criterion
The most critical formula for long-term survival, mathematically determining the optimal fraction of your capital to risk on a single trade.

Formula: $f^* = W - \frac{1 - W}{R}$

Calculation: $W$ represents your historical win rate (e.g., 0.60 for a 60% win rate), and $R$ represents your Reward-to-Risk ratio (e.g., 1.5).

Strategic Application: If the formula suggests allocating 33% of your account, doing so mathematically maximizes aggressive growth. However, to avoid severe drawdowns from standard market variance, professional traders apply a "Fractional Kelly" model, risking only 25% to 33% of the formula's suggested output on any given trade.

1. Dynamic Stop-Loss Placement: Average True Range (ATR)
Static percentage stop-losses often fail due to crypto's fluctuating volatility. The ATR calculates a dynamic stop-loss based on current market noise.

Formulas:
Long Position: $\text{Stop Loss} = \text{Entry Price} - (\text{ATR} \times \text{Multiplier})$

Short Position: $\text{Stop Loss} = \text{Entry Price} + (\text{ATR} \times \text{Multiplier})$

Calculation: The ATR is the moving average of the True Range (the greatest of the current high minus low, absolute high minus previous close, or absolute low minus previous close) over a set period, typically 14 days or intraday periods.

Strategic Application: Determine the current ATR value and apply a multiplier (usually 1.5 to 3). This gives your trade enough breathing room to survive natural intraday pullbacks without prematurely triggering your stop-loss.

1. Institutional Trend Identification: Volume-Weighted Average Price (VWAP)
VWAP is the benchmark used by institutional algorithms to determine the fair intraday value of an asset based on where the most volume was transacted.

Formula: $VWAP = \frac{\sum(\text{Price} \times \text{Volume})}{\sum \text{Volume}}$

Calculation: Multiply the price of each trade by its volume, sum these values, and divide by the total volume traded during the session.

Strategic Application: Treat the VWAP line as dynamic support and resistance. In a bullish setup, wait for the price to pull back and touch the VWAP. If the price bounces (rejects) off the VWAP on strong volume, execute a long entry and place your stop-loss just below the VWAP line.

1. Order Flow Aggression: Cumulative Volume Delta (CVD)
CVD uncovers the hidden battle between buyers and sellers by measuring aggressive market orders against passive limit orders.

Formula: $\Delta = V_{ask} - V_{bid}$

Calculation: Subtract the volume of aggressive sell orders (hitting the bid) from the volume of aggressive buy orders (hitting the ask). CVD continuously adds these delta values together bar after bar to plot a running total.

Strategic Application: Use CVD to spot divergence. If a cryptocurrency's price is making higher highs, but the CVD line is dropping, it indicates "exhaustion". The upward move lacks true buying pressure, signaling that a sharp bearish reversal is imminent.

1. Overbought/Oversold Momentum: Relative Strength Index (RSI)
RSI measures the velocity of price movements to identify when a short-term trend is overextended.

Formula: $\text{RSI} = 100 - \frac{100}{1 + RS}$

Calculation: $RS$ (Relative Strength) is the average of profitable price closes divided by the average of unprofitable price closes over a given timeframe.

Strategic Application: Never trade RSI in isolation. Use it in confluence with a macro-trend indicator like the MACD. If the higher timeframe confirms an uptrend, wait for the lower timeframe RSI to drop below 30 (oversold) and cross back up before executing a long entry, ensuring you are buying the temporary dip.

1. Market-Neutral Yield: Funding Rate Arbitrage
This formula enables traders to generate consistent, delta-neutral yield regardless of directional price action.

Formula: $\text{Funding Amount} = \text{Position Notional Value} \times \text{Funding Rate}$

Calculation: The funding rate is determined by the spread between the perpetual futures price and the spot index, plus interest components.

Strategic Application: If the funding rate is heavily positive (futures are trading higher than spot), buy the asset in the spot market and simultaneously open a short position of the exact same size in the perpetual futures market. Your price risk is neutralized, but you will continuously collect the funding payments every eight hours.

1. Risk-Adjusted Performance: The Sortino Ratio
While amateur traders focus on pure percentage returns, professionals evaluate strategies based on how much downside risk was required to achieve those returns.

Formula: $\text{Sortino Ratio} = \frac{R_p - R_f}{\sigma_d}$

Calculation: Subtract the risk-free rate ($R_f$) from the portfolio return ($R_p$), and divide the result by the downside deviation ($\sigma_d$).

Strategic Application: Unlike the Sharpe ratio, which penalizes all volatility, the Sortino ratio only penalizes downside volatility. Since crypto day trading strategies rely on massive upside variance (clumped, explosive wins), tracking your Sortino ratio tells you exactly how well your strategy protects your capital during drawdowns.
