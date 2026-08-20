"""
Layer 8: Quarantine Store

Manages quarantined extraction records with cold storage.
"""

import sqlite3
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
import structlog
from typing import Optional, List
from scraper.core.models import QuarantineRecord

logger = structlog.get_logger(__name__)

class QuarantineStore:
    """
    Manages quarantined extraction records with cold storage.
    """

    def __init__(self) -> None:
        self._db_path: Optional[str] = None
        self._cold_storage_path: Optional[str] = None
        self._conn: Optional[sqlite3.Connection] = None

    async def initialize(self, db_path: str, cold_storage_path: str) -> None:
        """Initialize QuarantineStore with DB and cold storage paths."""
        self._db_path = db_path
        self._cold_storage_path = cold_storage_path
        
        # Ensure cold storage directory exists
        os.makedirs(self._cold_storage_path, exist_ok=True)
        
        def _init_db() -> sqlite3.Connection:
            conn = sqlite3.connect(self._db_path)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS quarantine_records (
                    snapshot_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    page_url TEXT NOT NULL,
                    broken_selector TEXT,
                    proposed_selector TEXT,
                    confidence_score REAL,
                    quarantined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    retention_expires_at TIMESTAMP NOT NULL,
                    resolved INTEGER DEFAULT 0,
                    resolved_by TEXT,
                    resolved_at TIMESTAMP,
                    cold_storage_key TEXT
                )
            ''')
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_init_db)
        logger.info("initialized_quarantine_store", db_path=db_path, cold_storage_path=cold_storage_path)

    async def quarantine(self, record: QuarantineRecord, sanitized_ax_tree: str) -> str:
        """
        Quarantine a record and save the sanitized AXTree in cold storage.
        Returns the snapshot_id.
        """
        if not self._conn or not self._cold_storage_path:
            raise RuntimeError("QuarantineStore not initialized")
            
        snapshot_id = record.snapshot_id
        cold_storage_key = f"{snapshot_id}.json"
        cold_storage_file = os.path.join(self._cold_storage_path, cold_storage_key)
        
        now = datetime.now(timezone.utc)
        quarantined_at = now.isoformat()
        # 7-day retention
        retention_expires_at = (now + timedelta(days=7)).isoformat()
        
        def _save_cold_storage() -> None:
            data = {
                "snapshot_id": snapshot_id,
                "sanitized_ax_tree": sanitized_ax_tree,
                "quarantined_at": quarantined_at
            }
            with open(cold_storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        
        await asyncio.to_thread(_save_cold_storage)
        
        def _save_db() -> None:
            self._conn.execute('''
                INSERT OR REPLACE INTO quarantine_records (
                    snapshot_id, domain, field_name, page_url, broken_selector, 
                    proposed_selector, confidence_score, quarantined_at, 
                    retention_expires_at, resolved, cold_storage_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (
                snapshot_id, record.domain, record.field_name, record.page_url,
                record.broken_selector, record.proposed_selector,
                record.confidence_score, quarantined_at, retention_expires_at,
                cold_storage_key
            ))
            self._conn.commit()

        await asyncio.to_thread(_save_db)
        logger.info("record_quarantined", snapshot_id=snapshot_id, domain=record.domain)
        return snapshot_id

    async def resolve(self, snapshot_id: str, resolved_by: str) -> None:
        """Mark a quarantined record as resolved."""
        if not self._conn:
            raise RuntimeError("QuarantineStore not initialized")
            
        def _resolve() -> None:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute('''
                UPDATE quarantine_records 
                SET resolved = 1, resolved_by = ?, resolved_at = ? 
                WHERE snapshot_id = ?
            ''', (resolved_by, now, snapshot_id))
            self._conn.commit()

        await asyncio.to_thread(_resolve)
        logger.info("record_resolved", snapshot_id=snapshot_id, resolved_by=resolved_by)

    async def get_pending(self, domain: Optional[str] = None) -> List[QuarantineRecord]:
        """Get unresolved quarantined records."""
        if not self._conn:
            raise RuntimeError("QuarantineStore not initialized")
            
        def _get() -> List[QuarantineRecord]:
            if domain:
                cursor = self._conn.execute('''
                    SELECT snapshot_id, domain, field_name, page_url, broken_selector,
                           proposed_selector, confidence_score
                    FROM quarantine_records 
                    WHERE resolved = 0 AND domain = ?
                ''', (domain,))
            else:
                cursor = self._conn.execute('''
                    SELECT snapshot_id, domain, field_name, page_url, broken_selector,
                           proposed_selector, confidence_score
                    FROM quarantine_records 
                    WHERE resolved = 0
                ''')
            
            records = []
            for row in cursor.fetchall():
                records.append(QuarantineRecord(
                    snapshot_id=row[0],
                    domain=row[1],
                    field_name=row[2],
                    page_url=row[3],
                    broken_selector=row[4],
                    proposed_selector=row[5],
                    confidence_score=row[6]
                ))
            return records

        return await asyncio.to_thread(_get)

    async def get_record(self, snapshot_id: str) -> Optional[QuarantineRecord]:
        """Get a specific quarantined record by snapshot_id."""
        if not self._conn:
            raise RuntimeError("QuarantineStore not initialized")
            
        def _get() -> Optional[QuarantineRecord]:
            cursor = self._conn.execute('''
                SELECT snapshot_id, domain, field_name, page_url, broken_selector,
                       proposed_selector, confidence_score
                FROM quarantine_records 
                WHERE snapshot_id = ?
            ''', (snapshot_id,))
            
            row = cursor.fetchone()
            if row:
                return QuarantineRecord(
                    snapshot_id=row[0],
                    domain=row[1],
                    field_name=row[2],
                    page_url=row[3],
                    broken_selector=row[4],
                    proposed_selector=row[5],
                    confidence_score=row[6]
                )
            return None

        return await asyncio.to_thread(_get)

    async def cleanup_expired(self) -> int:
        """Delete records past retention and return count deleted."""
        if not self._conn or not self._cold_storage_path:
            raise RuntimeError("QuarantineStore not initialized")
            
        def _cleanup() -> int:
            now = datetime.now(timezone.utc).isoformat()
            
            # Find expired records
            cursor = self._conn.execute('''
                SELECT snapshot_id, cold_storage_key 
                FROM quarantine_records 
                WHERE retention_expires_at < ?
            ''', (now,))
            expired_records = cursor.fetchall()
            
            count = 0
            for snapshot_id, cold_storage_key in expired_records:
                # Delete cold storage file
                if cold_storage_key:
                    file_path = os.path.join(self._cold_storage_path, cold_storage_key)
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except OSError as e:
                        logger.warning("failed_to_delete_cold_storage", snapshot_id=snapshot_id, error=str(e))
                
                # Delete from DB
                self._conn.execute('DELETE FROM quarantine_records WHERE snapshot_id = ?', (snapshot_id,))
                count += 1
                
            self._conn.commit()
            return count

        count = await asyncio.to_thread(_cleanup)
        logger.info("cleaned_up_expired_records", count=count)
        return count

    async def get_snapshot_content(self, snapshot_id: str) -> Optional[str]:
        """Retrieve sanitized AXTree from cold storage."""
        if not self._conn or not self._cold_storage_path:
            raise RuntimeError("QuarantineStore not initialized")
            
        def _get_key() -> Optional[str]:
            cursor = self._conn.execute('SELECT cold_storage_key FROM quarantine_records WHERE snapshot_id = ?', (snapshot_id,))
            row = cursor.fetchone()
            return row[0] if row else None

        cold_storage_key = await asyncio.to_thread(_get_key)
        if not cold_storage_key:
            return None
            
        file_path = os.path.join(self._cold_storage_path, cold_storage_key)
        
        def _read_file() -> Optional[str]:
            if not os.path.exists(file_path):
                return None
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("sanitized_ax_tree")

        return await asyncio.to_thread(_read_file)
