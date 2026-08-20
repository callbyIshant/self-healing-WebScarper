"""
Async Redis wrapper.
"""
import structlog
import redis.asyncio as redis
from redis.exceptions import RedisError
from typing import Any, Optional, List

logger = structlog.get_logger()

class RedisClient:
    def __init__(self, url: str = 'redis://localhost:6379/0'):
        self.url = url
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connects to Redis."""
        try:
            self._client = redis.from_url(self.url, decode_responses=True)
            await self._client.ping()
            logger.info("RedisClient connected", url=self.url)
        except RedisError as e:
            logger.warning("RedisClient connection failed", error=str(e), url=self.url)
            self._client = None

    async def close(self) -> None:
        """Closes the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("RedisClient closed")

    async def execute_lua(self, script: str, keys: List[str], args: List[Any]) -> Any:
        """Executes a Lua script."""
        if not self._client:
            logger.warning("RedisClient not connected, skipping Lua execution")
            return None
        try:
            lua_script = self._client.register_script(script)
            return await lua_script(keys=keys, args=args)
        except RedisError as e:
            logger.warning("Lua execution failed", error=str(e))
            return None

    async def get(self, key: str) -> Optional[str]:
        """Gets a value by key."""
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except RedisError as e:
            logger.warning("Redis get failed", error=str(e), key=key)
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Sets a value with optional TTL."""
        if not self._client:
            return
        try:
            await self._client.set(key, value, ex=ttl)
        except RedisError as e:
            logger.warning("Redis set failed", error=str(e), key=key)

    async def is_available(self) -> bool:
        """Health check for Redis."""
        if not self._client:
            return False
        try:
            return await self._client.ping()
        except RedisError:
            return False

    def load_lua_script(self, script_path: str) -> str:
        """Loads a Lua script from file."""
        with open(script_path, 'r', encoding='utf-8') as f:
            return f.read()
