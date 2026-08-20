"""
Robots.txt checker complying with RFC 9309.
"""

import asyncio
import httpx
import structlog
from urllib.parse import urlparse
from datetime import datetime, timedelta
from typing import Dict, Optional, Union, Tuple

try:
    from protego import Protego
except ImportError:
    Protego = None

logger = structlog.get_logger()

class RobotsChecker:
    def __init__(self, cache_ttl_hours: int = 12):
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.cache: Dict[str, Tuple[Union['Protego', bool], datetime]] = {}
        # Max redirects capped to 5 per RFC requirements
        self.client = httpx.AsyncClient(max_redirects=5)

    async def is_allowed(self, url: str, user_agent: str = '*') -> bool:
        """
        Check if scraping the URL is allowed by robots.txt.
        """
        if not Protego:
            logger.warning("protego library not installed, defaulting to allowed")
            return True

        parsed = urlparse(url)
        domain = parsed.netloc
        
        # We don't want to block the hot path with HTTP requests, so if it's not cached,
        # we trigger a background fetch but might fail closed or open depending on policy.
        # For this implementation, we await the fetch if not cached.
        protego_obj_or_bool = await self._get_or_fetch_robots(domain, parsed.scheme)
        
        if isinstance(protego_obj_or_bool, bool):
            return protego_obj_or_bool
            
        if protego_obj_or_bool is not None:
            return protego_obj_or_bool.can_fetch(url, user_agent)
            
        return False # Fallback fail-closed

    async def get_crawl_delay(self, domain: str, user_agent: str = '*') -> Optional[float]:
        """
        Get the Crawl-delay directive for a domain and user agent.
        """
        if domain not in self.cache:
            return None
            
        protego_obj_or_bool, _ = self.cache.get(domain, (None, None))
        if protego_obj_or_bool is not None and not isinstance(protego_obj_or_bool, bool):
            delay = protego_obj_or_bool.crawl_delay(user_agent)
            if delay is not None:
                return float(delay)
        return None

    async def _get_or_fetch_robots(self, domain: str, scheme: str) -> Union['Protego', bool, None]:
        if domain in self.cache:
            obj, timestamp = self.cache[domain]
            if datetime.now() - timestamp < self.cache_ttl:
                return obj

        robots_url = f"{scheme}://{domain}/robots.txt"
        obj: Union['Protego', bool, None] = False
        
        try:
            response = await self.client.get(robots_url)
            if response.status_code >= 500:
                # Treats 5xx on robots.txt fetch as full disallow (per RFC 9309)
                obj = False 
            elif 400 <= response.status_code < 500 and response.status_code != 429:
                # Treats 4xx (except 429) as full allow
                obj = True
            else:
                if Protego:
                    obj = Protego.parse(response.text)
                else:
                    obj = True
        except Exception as e:
            logger.error("Failed to fetch robots.txt", domain=domain, error=str(e))
            obj = False # Fail closed
            
        self.cache[domain] = (obj, datetime.now())
        return obj

    async def refresh_robots(self, domain: str, scheme: str = "https") -> None:
        """
        Background refresh of robots.txt for a domain.
        Should be dispatched as an asyncio task.
        """
        await self._get_or_fetch_robots(domain, scheme)
