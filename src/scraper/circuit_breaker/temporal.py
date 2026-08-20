"""
Temporal Breaker Layer.

Responsible for per-field thrash control.
If a field requires frequent repairs within a short window, it transitions
to REQUIRES_HUMAN_INTERVENTION to block automated healing and prevent endless repair cycles.
"""
import asyncio
import aiosqlite
import structlog
from typing import Optional

from scraper.core.enums import BreakerState

logger = structlog.get_logger()

class TemporalBreaker:
    THRASH_LIMIT = 3
    WINDOW_HOURS = 48

    def __init__(self) -> None:
        self._db_path: Optional[str] = None

    async def initialize(self, db_path: str) -> None:
        """Initialize the temporal breaker state databases."""
        self._db_path = db_path
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS temporal_breaker_state (
                    domain TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'closed',
                    last_state_change_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reset_by TEXT,
                    reset_at TIMESTAMP,
                    PRIMARY KEY (domain, field_name)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS repair_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    repaired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    old_selector TEXT,
                    new_selector TEXT,
                    confidence_score REAL
                )
            """)
            await db.commit()

    async def get_state(self, domain: str, field_name: str) -> BreakerState:
        """Get the current state for a domain and field."""
        if not self._db_path:
            raise RuntimeError("TemporalBreaker not initialized")

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT state FROM temporal_breaker_state WHERE domain = ? AND field_name = ?", 
                (domain, field_name)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return BreakerState(row[0].upper())
                return BreakerState.CLOSED

    async def get_repair_count(self, domain: str, field_name: str, window_hours: int = 48) -> int:
        """Get the number of repairs for a field within the given window."""
        if not self._db_path:
            raise RuntimeError("TemporalBreaker not initialized")
            
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("""
                SELECT COUNT(*) FROM repair_history 
                WHERE domain = ? AND field_name = ? AND repaired_at >= datetime('now', '-' || ? || ' hours')
            """, (domain, field_name, window_hours)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def check_field(self, domain: str, field_name: str) -> BreakerState:
        """
        Check field status. Returns REQUIRES_HUMAN_INTERVENTION if thrashing is detected.
        """
        state = await self.get_state(domain, field_name)
        if state == BreakerState.REQUIRES_HUMAN_INTERVENTION:
            return state

        repairs = await self.get_repair_count(domain, field_name, self.WINDOW_HOURS)
        if repairs >= self.THRASH_LIMIT:
            if not self._db_path:
                raise RuntimeError("TemporalBreaker not initialized")
                
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("""
                    INSERT INTO temporal_breaker_state (domain, field_name, state, last_state_change_at)
                    VALUES (?, ?, 'requires_human_intervention', CURRENT_TIMESTAMP)
                    ON CONFLICT(domain, field_name) DO UPDATE SET 
                        state = 'requires_human_intervention',
                        last_state_change_at = CURRENT_TIMESTAMP
                """, (domain, field_name))
                await db.commit()
            
            logger.warning("temporal_thrash_limit_exceeded", domain=domain, field_name=field_name)
            return BreakerState.REQUIRES_HUMAN_INTERVENTION
            
        return BreakerState.CLOSED

    async def record_repair(self, domain: str, field_name: str, old_selector: str, new_selector: str, confidence: float) -> None:
        """Record a field repair attempt."""
        if not self._db_path:
            raise RuntimeError("TemporalBreaker not initialized")

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO repair_history (domain, field_name, old_selector, new_selector, confidence_score)
                VALUES (?, ?, ?, ?, ?)
            """, (domain, field_name, old_selector, new_selector, confidence))
            await db.commit()

    async def reset(self, domain: str, field_name: str, reset_by: str) -> None:
        """Reset the temporal breaker state after human intervention."""
        if not self._db_path:
            raise RuntimeError("TemporalBreaker not initialized")

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                UPDATE temporal_breaker_state 
                SET state = 'closed', reset_by = ?, reset_at = CURRENT_TIMESTAMP, last_state_change_at = CURRENT_TIMESTAMP
                WHERE domain = ? AND field_name = ?
            """, (reset_by, domain, field_name))
            await db.commit()
            
        logger.info("temporal_breaker_reset", domain=domain, field_name=field_name, reset_by=reset_by)
