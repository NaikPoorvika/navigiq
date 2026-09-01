from redis.asyncio import Redis
from app.config import settings

# Global Redis client
redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

async def get_redis():
    """Dependency to get redis client."""
    return redis_client
