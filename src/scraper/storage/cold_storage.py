"""
Local filesystem cold storage for quarantined snapshots.
"""
import os
import json
import time
import glob
import structlog
import aiofiles

logger = structlog.get_logger()

class ColdStorage:
    def __init__(self, base_path: str = 'data/cold_storage'):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    def _get_path(self, snapshot_id: str) -> str:
        return os.path.join(self.base_path, f"{snapshot_id}.json")

    async def store(self, snapshot_id: str, data: dict) -> str:
        """Writes JSON file, returns key."""
        path = self._get_path(snapshot_id)
        async with aiofiles.open(path, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=2))
        logger.info("Stored snapshot in cold storage", snapshot_id=snapshot_id)
        return snapshot_id

    async def retrieve(self, snapshot_id: str) -> dict | None:
        """Reads JSON file."""
        path = self._get_path(snapshot_id)
        if not os.path.exists(path):
            return None
        try:
            async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except Exception as e:
            logger.error("Failed to retrieve snapshot", snapshot_id=snapshot_id, error=str(e))
            return None

    async def delete(self, snapshot_id: str) -> bool:
        """Deletes file."""
        path = self._get_path(snapshot_id)
        if os.path.exists(path):
            try:
                os.remove(path)
                logger.info("Deleted snapshot from cold storage", snapshot_id=snapshot_id)
                return True
            except OSError as e:
                logger.error("Failed to delete snapshot", snapshot_id=snapshot_id, error=str(e))
                return False
        return False

    async def cleanup_expired(self, max_age_days: int = 7) -> int:
        """Deletes files older than TTL, returns count."""
        count = 0
        now = time.time()
        max_age_seconds = max_age_days * 86400
        
        pattern = os.path.join(self.base_path, "*.json")
        for file_path in glob.glob(pattern):
            try:
                if os.path.isfile(file_path):
                    mtime = os.path.getmtime(file_path)
                    if now - mtime > max_age_seconds:
                        os.remove(file_path)
                        count += 1
            except OSError as e:
                logger.error("Failed to clean up file", file_path=file_path, error=str(e))
        
        if count > 0:
            logger.info("Cleaned up expired snapshots", count=count, max_age_days=max_age_days)
        return count
