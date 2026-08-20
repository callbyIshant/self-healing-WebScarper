import pytest
from datetime import datetime, timezone
import fakeredis
from scraper.core.models import (
    DomainConfig, FieldDefinition, LKGSnapshot, ExtractionResult,
    BusinessRulesConfig, VolatilityProfilesConfig
)
from scraper.core.enums import ScrapingPosture

@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test.db")

@pytest.fixture
def sample_field():
    return FieldDefinition(
        name="title",
        primary_selector="h1",
        description="Book title",
        type="string"
    )

@pytest.fixture
def sample_domain_config(sample_field):
    return DomainConfig(
        domain="books.toscrape.com",
        posture=ScrapingPosture.LAX,
        fields=[sample_field]
    )

@pytest.fixture
def sample_lkg_snapshot(sample_field):
    return LKGSnapshot(
        snapshot_id="snap-123",
        domain="books.toscrape.com",
        timestamp=datetime.now(timezone.utc),
        selectors={"title": sample_field}
    )

@pytest.fixture
def sample_extraction_result():
    return ExtractionResult(
        snapshot_id="snap-123",
        domain="books.toscrape.com",
        timestamp=datetime.now(timezone.utc),
        data={"title": "A Light in the Attic"},
        metadata={}
    )

@pytest.fixture
def sample_business_rules():
    return BusinessRulesConfig(rules=[])

@pytest.fixture
def sample_volatility_profiles():
    return VolatilityProfilesConfig(profiles=[])

@pytest.fixture
def mock_redis():
    return fakeredis.FakeRedis()

@pytest.fixture
def event_loop():
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
