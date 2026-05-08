import json

import pytest

from app.streaming.publisher import RedisPublisher


class FakeRedis:
    def __init__(self):
        self.set_calls = []
        self.publish_calls = []
        self.xadd_calls = []

    async def set(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))

    async def publish(self, *args, **kwargs):
        self.publish_calls.append((args, kwargs))

    async def xadd(self, *args, **kwargs):
        self.xadd_calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_publish_quote_writes_cache_pubsub_and_stream():
    redis = FakeRedis()
    publisher = RedisPublisher(redis)

    await publisher.publish_quote(
        exchange="okx",
        symbol="BTC-USDT",
        ts=1700000000.0,
        recv_ts=1700000000.5,
        bid=99.0,
        ask=101.0,
        bid_size=1.0,
        ask_size=2.0,
    )

    assert redis.set_calls[0][0][0] == "latest_quote:okx:BTC-USDT"
    cached = json.loads(redis.set_calls[0][0][1])
    assert cached["mid"] == 100.0
    assert cached["spread_bps"] == 200.0
    assert redis.publish_calls[0][0][0] == "quotes:okx:BTC-USDT"
    assert redis.xadd_calls[0][0][0] == "market_quotes"
    stream_fields = redis.xadd_calls[0][0][1]
    assert stream_fields["bid"] == "99.0"
    assert stream_fields["ask"] == "101.0"
