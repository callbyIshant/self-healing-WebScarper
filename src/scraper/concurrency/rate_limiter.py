"""
Distributed rate limiter using Redis Lua token bucket, with local fallback.
"""

import os
import time
import asyncio
import structlog
from typing import Optional, Tuple, Dict, Any

logger = structlog.get_logger()

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

class LocalTokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> Tuple[bool, float]:
        """Returns (allowed, wait_seconds)"""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            refill_amount = elapsed * self.refill_rate
            
            if refill_amount > 0:
                self.tokens = min(float(self.capacity), self.tokens + refill_amount)
                self.last_refill = now
                
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0
            else:
                wait_time = (tokens - self.tokens) / self.refill_rate
                return False, wait_time


class DistributedRateLimiter:
    def __init__(self, redis_url: str = "redis://localhost:6379/0", lua_script_path: str = "src/scraper/concurrency/lua/token_bucket.lua"):
        self.redis = redis.from_url(redis_url) if redis else None
        self.lua_script_path = lua_script_path
        self._script_sha: Optional[str] = None
        self.local_buckets: Dict[str, LocalTokenBucket] = {}
        self.domain_configs: Dict[str, Dict[str, Any]] = {}
        
    async def _load_script(self) -> None:
        if not self.redis:
            return
            
        if self._script_sha is None:
            try:
                # Read relative to the execution root, assuming it's available
                with open(self.lua_script_path, "r") as f:
                    script_content = f.read()
                self._script_sha = await self.redis.script_load(script_content)
            except Exception as e:
                logger.error("Failed to load Lua script", error=str(e))
                self.redis = None # Fallback to local

    async def set_domain_rate(self, domain: str, rpm: int, burst: int) -> None:
        """Configures per-domain rate from DomainConfig."""
        refill_rate = rpm / 60.0
        self.domain_configs[domain] = {"capacity": burst, "refill_rate": refill_rate}
        
        if not self.redis:
            self.local_buckets[domain] = LocalTokenBucket(burst, refill_rate)

    async def set_manifest_expiry(self, domain: str, expiry_timestamp: float) -> None:
        """Sets manifest expiry in Redis to be checked atomically."""
        if self.redis:
            await self.redis.set(f"manifest_expiry:{domain}", str(expiry_timestamp))

    async def acquire_token(self, domain: str, tokens: int = 1) -> Tuple[bool, float]:
        """
        Wraps atomic Redis Lua token bucket for distributed rate limiting.
        Also checks manifest expiration in the same Redis round-trip.
        """
        if not self.redis:
            return await self._local_acquire(domain, tokens)
            
        await self._load_script()
        
        # If script failed to load and disabled Redis
        if not self.redis or not self._script_sha:
            return await self._local_acquire(domain, tokens)
        
        config = self.domain_configs.get(domain, {"capacity": 10, "refill_rate": 1.0})
        bucket_key = f"rate_limit:{domain}"
        expiry_key = f"manifest_expiry:{domain}"
        
        try:
            result = await self.redis.evalsha(
                self._script_sha,
                2,
                bucket_key,
                expiry_key,
                config["capacity"],
                config["refill_rate"],
                tokens
            )
            
            allowed, remaining, wait_seconds = result
            
            # Sentinel value from Lua script indicating expired manifest
            if allowed == 0 and remaining == 0 and wait_seconds == -1:
                logger.warning("Manifest expired check failed in Lua script", domain=domain)
                return False, -1.0 
                
            return bool(allowed), float(wait_seconds)
            
        except Exception as e:
            logger.error("Redis Lua rate limiting failed, falling back to local", error=str(e))
            self.redis = None # Disable redis on error
            return await self._local_acquire(domain, tokens)
            
    async def _local_acquire(self, domain: str, tokens: int) -> Tuple[bool, float]:
        """Fallback to in-memory token bucket per worker (fail-throttled)."""
        if domain not in self.local_buckets:
            config = self.domain_configs.get(domain, {"capacity": 10, "refill_rate": 1.0})
            self.local_buckets[domain] = LocalTokenBucket(config["capacity"], config["refill_rate"])
        return await self.local_buckets[domain].acquire(tokens)
