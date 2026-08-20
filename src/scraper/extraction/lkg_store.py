"""
Last Known Good (LKG) store for tracking successful extractions.
"""
import json
from typing import List, Optional

import aiosqlite
import structlog

from scraper.core.enums import SelectorStrategy
from scraper.core.models import LKGSnapshot

logger = structlog.get_logger(__name__)


class LKGStore:
    """
    Manages a sliding window of 5 LKG snapshots per selector in SQLite.
    """
    def __init__(self) -> None:
        self.db_path: Optional[str] = None

    async def initialize(self, db_path: str) -> None:
        """
        Initialize the SQLite database.
        """
        self.db_path = db_path
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS lkg_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    selector TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    ax_tree_neighborhood TEXT NOT NULL,
                    text_signature TEXT NOT NULL,
                    sample_value TEXT,
                    page_url TEXT,
                    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_lkg_domain_field ON lkg_snapshots(domain, field_name)')
            await db.commit()
        logger.info("lkg_store_initialized", db_path=db_path)

    async def push_snapshot(self, snapshot: LKGSnapshot) -> None:
        """
        Append a snapshot, evicting the oldest if >5 per domain+field.
        """
        if not self.db_path:
            raise RuntimeError("LKGStore not initialized")
            
        async with aiosqlite.connect(self.db_path) as db:
            sample_value_str = json.dumps(snapshot.sample_value)
            
            await db.execute('''
                INSERT INTO lkg_snapshots (
                    domain, field_name, selector, strategy, ax_tree_neighborhood, 
                    text_signature, sample_value, page_url, snapshot_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                snapshot.domain, snapshot.field_name, snapshot.selector, 
                snapshot.strategy.value, snapshot.ax_tree_neighborhood, 
                snapshot.text_signature, sample_value_str, snapshot.page_url,
                snapshot.snapshot_at
            ))
            
            # Enforce sliding window of 5
            await db.execute('''
                DELETE FROM lkg_snapshots 
                WHERE id NOT IN (
                    SELECT id FROM lkg_snapshots 
                    WHERE domain = ? AND field_name = ? 
                    ORDER BY snapshot_at DESC 
                    LIMIT 5
                ) 
                AND domain = ? AND field_name = ?
            ''', (snapshot.domain, snapshot.field_name, snapshot.domain, snapshot.field_name))
            
            await db.commit()
            
        logger.debug("pushed_lkg_snapshot", domain=snapshot.domain, field_name=snapshot.field_name)

    async def get_latest(self, domain: str, field_name: str) -> Optional[LKGSnapshot]:
        """
        Get the most recent LKG snapshot.
        """
        history = await self.get_history(domain, field_name, limit=1)
        return history[0] if history else None

    async def get_history(self, domain: str, field_name: str, limit: int = 5) -> List[LKGSnapshot]:
        """
        Get history of snapshots for a domain/field.
        """
        if not self.db_path:
            raise RuntimeError("LKGStore not initialized")
            
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT * FROM lkg_snapshots 
                WHERE domain = ? AND field_name = ? 
                ORDER BY snapshot_at DESC 
                LIMIT ?
            ''', (domain, field_name, limit))
            
            rows = await cursor.fetchall()
            
            results = []
            for row in rows:
                results.append(LKGSnapshot(
                    domain=row['domain'],
                    field_name=row['field_name'],
                    selector=row['selector'],
                    strategy=SelectorStrategy(row['strategy']),
                    ax_tree_neighborhood=row['ax_tree_neighborhood'],
                    text_signature=row['text_signature'],
                    sample_value=json.loads(row['sample_value']) if row['sample_value'] else None,
                    page_url=row['page_url'],
                    snapshot_at=row['snapshot_at']
                ))
                
            return results

    async def rollback(self, domain: str, field_name: str, steps: int = 1) -> Optional[LKGSnapshot]:
        """
        Rollback N steps by deleting newest N snapshots and returning the new latest.
        """
        if not self.db_path:
            raise RuntimeError("LKGStore not initialized")
            
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                DELETE FROM lkg_snapshots 
                WHERE id IN (
                    SELECT id FROM lkg_snapshots 
                    WHERE domain = ? AND field_name = ? 
                    ORDER BY snapshot_at DESC 
                    LIMIT ?
                )
            ''', (domain, field_name, steps))
            
            await db.commit()
            
        logger.info("rolled_back_snapshots", domain=domain, field_name=field_name, steps=steps)
        return await self.get_latest(domain, field_name)
