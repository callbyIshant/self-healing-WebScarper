import math
import sqlite3
import structlog
import aiosqlite
from typing import Any

from scraper.core.models import ValidationResult, VolatilityProfileConfig, VolatilityProfilesConfig
from scraper.core.enums import ValidationCheckType, VolatilityProfile

logger = structlog.get_logger(__name__)

class StatisticalValidator:
    """
    Validates numeric values against historical distributions to detect anomalous shifts.
    Maintains rolling statistics using Welford's online algorithm.
    """

    def __init__(self, profiles: VolatilityProfilesConfig):
        """
        Initialize the statistical validator with volatility profile configs.
        
        Args:
            profiles: Configuration mapping VolatilityProfile enums to their parameters (like sigma_threshold).
        """
        self.profiles = profiles
        self.db_path: str | None = None

    async def initialize(self, db_path: str) -> None:
        """
        Initializes the SQLite database and creates the stats table if it doesn't exist.
        
        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS field_statistics (
                    domain TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    value_count INTEGER DEFAULT 0,
                    value_sum REAL DEFAULT 0,
                    value_sum_sq REAL DEFAULT 0,
                    last_value REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (domain, field_name, item_key)
                )
            ''')
            await db.commit()

    async def validate(self, domain: str, field_name: str, item_key: str, value: float, volatility: VolatilityProfile, dom_context: str | None = None) -> ValidationResult:
        """
        Validates a value against its historical distribution.
        
        Args:
            domain: The site domain.
            field_name: The field being validated.
            item_key: The specific item identifier.
            value: The current extracted numeric value.
            volatility: The volatility profile assigned to this field.
            dom_context: Optional context from the DOM (e.g., 'Sale' label).
            
        Returns:
            ValidationResult indicating if the value falls within normal statistical bounds.
        """
        if self.db_path is None:
            raise RuntimeError("StatisticalValidator not initialized with db_path")
            
        stats = await self.get_stats(domain, field_name, item_key)
        
        # If we don't have enough data points, we default to valid (allow learning)
        if stats["count"] < 2:
            return ValidationResult(
                is_valid=True,
                check_type=ValidationCheckType.STATISTICAL,
                message="Insufficient data for statistical validation"
            )
            
        mean = stats["mean"]
        stddev = stats["stddev"]
        
        # Avoid division by zero if all historical values are identical
        if stddev < 1e-6:
            stddev = 1e-6

        z_score = abs(value - mean) / stddev
        
        # Get threshold from config or use a sane default
        threshold = 3.0
        if self.profiles and hasattr(self.profiles, "profiles"):
            profile_config = self.profiles.profiles.get(volatility.name)
            if profile_config and hasattr(profile_config, "sigma_threshold"):
                threshold = getattr(profile_config, "sigma_threshold")

        is_valid = z_score <= threshold
        
        message = f"Z-score {z_score:.2f} within threshold {threshold}"
        if not is_valid:
            message = f"Z-score {z_score:.2f} exceeds threshold {threshold}"
            if dom_context:
                message += f" (Note: DOM context indicated '{dom_context}')"

        return ValidationResult(
            is_valid=is_valid,
            check_type=ValidationCheckType.STATISTICAL,
            message=message
        )

    async def update_stats(self, domain: str, field_name: str, item_key: str, value: float) -> None:
        """
        Updates the rolling statistics for a specific field using Welford's algorithm formulation 
        (or sum/sum_sq for simplicity given SQLite storage).
        """
        if self.db_path is None:
            raise RuntimeError("StatisticalValidator not initialized with db_path")

        async with aiosqlite.connect(self.db_path) as db:
            # Upsert the new value
            await db.execute('''
                INSERT INTO field_statistics (domain, field_name, item_key, value_count, value_sum, value_sum_sq, last_value)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(domain, field_name, item_key) DO UPDATE SET
                    value_count = value_count + 1,
                    value_sum = value_sum + excluded.value_sum,
                    value_sum_sq = value_sum_sq + excluded.value_sum_sq,
                    last_value = excluded.last_value,
                    updated_at = CURRENT_TIMESTAMP
            ''', (domain, field_name, item_key, value, value ** 2, value))
            await db.commit()

    async def get_stats(self, domain: str, field_name: str, item_key: str) -> dict[str, Any]:
        """
        Retrieves the mean, standard deviation, and count for a specific field.
        """
        if self.db_path is None:
            raise RuntimeError("StatisticalValidator not initialized with db_path")
            
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT value_count, value_sum, value_sum_sq 
                FROM field_statistics 
                WHERE domain = ? AND field_name = ? AND item_key = ?
            ''', (domain, field_name, item_key))
            row = await cursor.fetchone()
            
            if not row:
                return {"mean": 0.0, "stddev": 0.0, "count": 0}
                
            count = row["value_count"]
            if count == 0:
                return {"mean": 0.0, "stddev": 0.0, "count": 0}
                
            sum_val = row["value_sum"]
            sum_sq_val = row["value_sum_sq"]
            
            mean = sum_val / count
            
            if count < 2:
                stddev = 0.0
            else:
                # Variance = (sum_sq - (sum^2 / count)) / (count - 1)
                variance = (sum_sq_val - (sum_val ** 2 / count)) / (count - 1)
                if variance < 0: 
                    variance = 0 # Handle floating point inaccuracies
                stddev = math.sqrt(variance)
                
            return {"mean": mean, "stddev": stddev, "count": count}
