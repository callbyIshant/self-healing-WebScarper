"""
SQLite store for unified async access.
"""
import os
import aiosqlite
import structlog
from typing import Optional

logger = structlog.get_logger()

class SQLiteStore:
    def __init__(self, db_path: str = 'data/scraper.db'):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initializes the database connection, creates tables and sets WAL mode."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        
        # We would create tables for LKGStore, circuit breakers, statistics here
        # E.g., await self._conn.execute("CREATE TABLE IF NOT EXISTS lkg_store ...")
        
        await self._conn.commit()
        logger.info("SQLiteStore initialized", db_path=self.db_path)

    async def get_connection(self) -> aiosqlite.Connection:
        """Returns the shared connection."""
        if not self._conn:
            raise RuntimeError("SQLiteStore is not initialized. Call initialize() first.")
        return self._conn

    async def close(self) -> None:
        """Closes the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("SQLiteStore closed")
