"""
Storage module for the self-healing web scraper.
"""
from scraper.storage.sqlite_store import SQLiteStore
from scraper.storage.redis_client import RedisClient
from scraper.storage.cold_storage import ColdStorage

__all__ = ["SQLiteStore", "RedisClient", "ColdStorage"]
