"""
Spatial Breaker Layer.

Responsible for detecting blast-radius level drift across a domain.
If a high percentage of fields fail extraction concurrently, it triggers a debounce
and eventually trips the circuit breaker to prevent further scraping until resolved.
"""
import asyncio
import json
import structlog
import aiosqlite
from typing import Optional, Dict, Any

from scraper.core.enums import BreakerState, DriftType
from scraper.core.exceptions import CircuitBreakerOpenError

logger = structlog.get_logger()

class SpatialBreaker:
    GLOBAL_DRIFT_THRESHOLD = 0.4
    DEBOUNCE_RETRIES = 3
    DEBOUNCE_PAUSE_SECONDS = 5.0

    def __init__(self) -> None:
        self._db_path: Optional[str] = None

    async def initialize(self, db_path: str) -> None:
        """Initialize the spatial breaker state database."""
        self._db_path = db_path
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS spatial_breaker_state (
                    domain TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'closed',
                    failed_ratio REAL DEFAULT 0,
                    consecutive_global_failures INTEGER DEFAULT 0,
                    last_failure_at TIMESTAMP,
                    last_state_change_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSON
                )
            """)
            await db.commit()

    async def get_state(self, domain: str) -> BreakerState:
        """Get the current circuit breaker state for a domain."""
        if not self._db_path:
            raise RuntimeError("SpatialBreaker not initialized")
            
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT state FROM spatial_breaker_state WHERE domain = ?", (domain,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return BreakerState(row[0].upper())
                return BreakerState.CLOSED

    async def transition_to(self, domain: str, new_state: BreakerState) -> None:
        """Transition the circuit breaker to a new state for the given domain."""
        if not self._db_path:
            raise RuntimeError("SpatialBreaker not initialized")

        state_str = new_state.name.lower()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO spatial_breaker_state (domain, state, last_state_change_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(domain) DO UPDATE SET 
                    state = excluded.state,
                    last_state_change_at = CURRENT_TIMESTAMP
            """, (domain, state_str))
            await db.commit()
            
        logger.info("spatial_breaker_transition", domain=domain, new_state=new_state.name)

    async def check_and_classify(self, domain: str, total_fields: int, failed_fields: int) -> DriftType:
        """
        Check the failure ratio. If it exceeds threshold, initiate debounce or classify as global drift.
        """
        if total_fields == 0:
            return DriftType.LOCAL

        ratio = failed_fields / total_fields
        if ratio <= self.GLOBAL_DRIFT_THRESHOLD:
            return DriftType.LOCAL
            
        logger.warning("spatial_drift_detected", domain=domain, ratio=ratio)
        return DriftType.GLOBAL

    async def run_debounce(self, domain: str, retry_count: int = 3) -> bool:
        """
        Runs a debounce pause and evaluates if retries are exhausted.
        Returns False if caller should retry, True if retries are exhausted and state becomes OPEN.
        """
        logger.info("spatial_debounce_start", domain=domain, retry_count=retry_count)
        
        if not self._db_path:
            raise RuntimeError("SpatialBreaker not initialized")

        await asyncio.sleep(self.DEBOUNCE_PAUSE_SECONDS)
        
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT consecutive_global_failures FROM spatial_breaker_state WHERE domain = ?", (domain,)
            ) as cursor:
                row = await cursor.fetchone()
                current_failures = row[0] if row else 0

            new_failures = current_failures + 1

            if new_failures >= retry_count:
                await db.execute("""
                    INSERT INTO spatial_breaker_state (domain, consecutive_global_failures)
                    VALUES (?, ?)
                    ON CONFLICT(domain) DO UPDATE SET 
                        consecutive_global_failures = excluded.consecutive_global_failures
                """, (domain, new_failures))
                await db.commit()
                
                await self.transition_to(domain, BreakerState.OPEN)
                logger.error("spatial_breaker_tripped", domain=domain, message="Requires human intervention")
                return True
                
            else:
                await db.execute("""
                    INSERT INTO spatial_breaker_state (domain, consecutive_global_failures)
                    VALUES (?, ?)
                    ON CONFLICT(domain) DO UPDATE SET 
                        consecutive_global_failures = excluded.consecutive_global_failures
                """, (domain, new_failures))
                await db.commit()
                return False

    async def reset(self, domain: str, reset_by: str) -> None:
        """Reset the breaker for a domain to CLOSED state (manual human intervention)."""
        if not self._db_path:
            raise RuntimeError("SpatialBreaker not initialized")

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                UPDATE spatial_breaker_state 
                SET state = 'closed', consecutive_global_failures = 0, last_state_change_at = CURRENT_TIMESTAMP
                WHERE domain = ?
            """, (domain,))
            await db.commit()
        
        logger.info("spatial_breaker_reset", domain=domain, reset_by=reset_by)
