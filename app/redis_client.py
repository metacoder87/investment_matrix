import redis.asyncio as redis
from .config import settings


class RedisClient:
    """
    A singleton-like class to manage the Redis connection pool.
    """

    _redis_pool = None

    @classmethod
    def get_redis(cls) -> redis.Redis:
        """
        Returns a Redis connection from the connection pool.
        Initializes the pool if it doesn't exist.
        """
        if cls._redis_pool is None:
            cls._redis_pool = redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
        return cls._redis_pool


redis_client = RedisClient.get_redis()