"""
Layer 7: Cross-Validation

This layer is responsible for verifying proposed selectors against multiple holdout pages
to detect overfit repairs.
"""

import sqlite3
import asyncio
from datetime import datetime, timezone
import structlog
from typing import Tuple, List, Optional
from scraper.core.models import FieldDefinition
from scraper.core.enums import SelectorStrategy
from scraper.validation.type_validator import TypeValidator

logger = structlog.get_logger(__name__)


class CrossValidator:
    """
    Verifies proposed selectors against multiple holdout pages to detect overfit repairs.
    """

    def __init__(self) -> None:
        self._db_path: Optional[str] = None
        self._conn: Optional[sqlite3.Connection] = None
        self.validator = TypeValidator()

    async def initialize(self, db_path: str) -> None:
        """Initialize the CrossValidator with an SQLite database path."""
        self._db_path = db_path
        
        def _init_db() -> sqlite3.Connection:
            conn = sqlite3.connect(self._db_path)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS holdout_pages (
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    last_fetched_at TIMESTAMP,
                    html_snapshot TEXT,
                    PRIMARY KEY (domain, url)
                )
            ''')
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_init_db)
        logger.info("initialized_cross_validator", db_path=db_path)

    async def validate_selector(
        self,
        domain: str,
        field: FieldDefinition,
        proposed_selector: str,
        strategy: SelectorStrategy,
        holdout_urls: List[str],
        browser_context
    ) -> Tuple[bool, int, int]:
        """
        Executes proposed selector against each holdout page.
        Requires schema-conformant extraction on holdout pages.
        Returns: (passed, passed_count, total_count)
        """
        if not holdout_urls:
            # If no holdout URLs are configured, pass with default count
            return True, 1, 1

        passed_count = 0
        total_count = 0
        loaded_count = 0

        for url in holdout_urls:
            page = None
            try:
                page = await browser_context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                loaded_count += 1
                
                # Fetch text content using selector
                try:
                    locator = page.locator(proposed_selector)
                    extracted_value = await locator.first.text_content(timeout=5000)
                except Exception:
                    extracted_value = None

                if extracted_value is not None and extracted_value.strip():
                    val_res = self.validator.validate(field, extracted_value.strip())
                    if val_res.passed:
                        passed_count += 1

                total_count += 1
            except Exception as e:
                logger.warning("holdout_page_failed_to_load", url=url, error=str(e))
            finally:
                if page:
                    await page.close()

        if loaded_count == 0:
            logger.warning("no_holdout_pages_could_be_loaded", domain=domain)
            return False, 0, total_count

        passed = (passed_count == total_count) and (total_count > 0)
        return passed, passed_count, total_count

    async def check_uniform_failure(self, domain: str, passed_count: int, total_count: int) -> bool:
        """
        Returns True if ALL holdout pages failed (site-wide change signal).
        """
        is_uniform_failure = (passed_count == 0 and total_count > 0)
        if is_uniform_failure:
             logger.info("uniform_failure_detected", domain=domain)
        return is_uniform_failure

    async def cache_holdout_page(self, domain: str, url: str, html: str) -> None:
        """Cache HTML for holdout page."""
        if not self._conn:
            raise RuntimeError("CrossValidator not initialized")
            
        def _cache() -> None:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute('''
                INSERT INTO holdout_pages (domain, url, last_fetched_at, html_snapshot)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(domain, url) DO UPDATE SET
                    last_fetched_at = excluded.last_fetched_at,
                    html_snapshot = excluded.html_snapshot
            ''', (domain, url, now, html))
            self._conn.commit()

        await asyncio.to_thread(_cache)

    async def get_holdout_urls(self, domain: str) -> List[str]:
        """Get cached holdout URLs."""
        if not self._conn:
            raise RuntimeError("CrossValidator not initialized")
            
        def _get() -> List[str]:
            cursor = self._conn.execute('SELECT url FROM holdout_pages WHERE domain = ?', (domain,))
            return [row[0] for row in cursor.fetchall()]

        return await asyncio.to_thread(_get)
