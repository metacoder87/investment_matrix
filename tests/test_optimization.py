import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.instrument import Price
from app.signals.engine import Signal, SignalType


class FakeRedisCache:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value
        return True

    async def publish(self, channel: str, payload: str):
        self.published.append((channel, payload))
        return 1


def _seed_prices(db_session, symbol: str = "BTC-USD", exchange: str = "coinbase", count: int = 80):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for idx in range(count):
        price = 100 + idx
        ts = start + timedelta(minutes=idx)
        db_session.add(
            Price(
                symbol=symbol,
                exchange=exchange,
                timestamp=ts,
                open=price - 0.5,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=10 + idx,
            )
        )
    db_session.commit()


def test_analysis_endpoint_caching(client, db_session):
    _seed_prices(db_session)
    cache = FakeRedisCache()

    def fake_add_technical_indicators(df):
        result = df.copy()
        result["rsi"] = 55.0
        result["macd"] = 1.0
        result["macdsignal"] = 0.5
        result["macdhist"] = 0.5
        result["bbands_upper"] = result["close"] + 1.0
        result["bbands_middle"] = result["close"]
        result["bbands_lower"] = result["close"] - 1.0
        result["sma_50"] = result["close"].rolling(window=1).mean()
        result["obv"] = 1.0
        result["atr"] = 1.0
        result["TSI_13_25_13"] = 0.0
        return result

    with patch("app.main.redis_client", cache), patch(
        "app.main.add_technical_indicators",
        side_effect=fake_add_technical_indicators,
    ) as mock_analysis:
        response1 = client.get("/api/coin/BTC-USD/analysis")
        response2 = client.get("/api/coin/BTC-USD/analysis")

    assert response1.status_code == 200
    assert response2.status_code == 200
    payload1 = response1.json()
    payload2 = response2.json()
    assert payload1["calculated_at"] == payload2["calculated_at"]
    assert len(payload1["data"]) == 80
    assert mock_analysis.call_count == 1
    assert cache.published


def test_quant_endpoint_caching(client, db_session):
    _seed_prices(db_session)
    cache = FakeRedisCache()
    metrics = {
        "annualized_volatility": 0.2,
        "sharpe_ratio": 1.1,
        "sortino_ratio": 1.4,
        "max_drawdown": -0.1,
        "calmar_ratio": 2.0,
        "omega_ratio": None,
        "skewness": 0.1,
        "kurtosis": -0.2,
    }

    with patch("app.main.redis_client", cache), patch(
        "app.main.calculate_risk_metrics",
        return_value=metrics,
    ) as mock_quant:
        response1 = client.get("/api/coin/BTC-USD/quant")
        response2 = client.get("/api/coin/BTC-USD/quant")

    assert response1.status_code == 200
    assert response2.status_code == 200
    payload1 = response1.json()
    payload2 = response2.json()
    assert payload1["calculated_at"] == payload2["calculated_at"]
    assert payload1["data"] == metrics
    assert mock_quant.call_count == 1


def test_signals_batch_caching(client):
    cache = FakeRedisCache()
    signal = Signal(
        symbol="BTC-USD",
        signal_type=SignalType.BUY,
        confidence=0.75,
        price=101.0,
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        reasons=["Test signal"],
        indicators={"rsi": 55.0},
        risk_reward=2.0,
        target_price=110.0,
        stop_loss=95.0,
    )

    with patch("app.main.redis_client", cache), patch(
        "app.main.SignalEngine.generate_signals_batch",
        return_value=[copy.deepcopy(signal)],
    ) as mock_batch:
        response1 = client.get("/api/signals/batch?symbols=BTC-USD")
        response2 = client.get("/api/signals/batch?symbols=BTC-USD")

    assert response1.status_code == 200
    assert response2.status_code == 200
    payload1 = response1.json()
    payload2 = response2.json()
    assert payload1["calculated_at"] == payload2["calculated_at"]
    assert payload1["count"] == 1
    assert payload1["signals"][0]["symbol"] == "BTC-USD"
    assert mock_batch.call_count == 1
