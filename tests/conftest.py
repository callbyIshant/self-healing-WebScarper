"""Shared pytest fixtures for the self-healing web scraper test suite."""

import asyncio
from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from scraper.core.enums import (
    ScrapingPosture,
    SelectorStrategy,
    VolatilityProfile,
)
from scraper.core.models import (
    BusinessRule,
    BusinessRulesConfig,
    DomainConfig,
    ExtractionResult,
    FieldDefinition,
    LKGSnapshot,
    VolatilityProfileConfig,
    VolatilityProfilesConfig,
)


@pytest.fixture
def tmp_db_path(tmp_path):
    """Temporary SQLite database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def sample_field():
    """A FieldDefinition matching the actual Pydantic model."""
    return FieldDefinition(
        name="title",
        selector="h1",
        strategy=SelectorStrategy.CSS,
        field_type="string",
        volatility=VolatilityProfile.LOW,
        required=True,
        description="Book title",
    )


@pytest.fixture
def sample_price_field():
    """A numeric FieldDefinition for price testing."""
    return FieldDefinition(
        name="price",
        selector=".price_color",
        strategy=SelectorStrategy.CSS,
        field_type="float",
        volatility=VolatilityProfile.MEDIUM,
        required=True,
        description="Book price in GBP",
    )


@pytest.fixture
def sample_domain_config(sample_field, sample_price_field):
    """A DomainConfig matching the actual Pydantic model."""
    return DomainConfig(
        domain="books.toscrape.com",
        rate_limit_rpm=20,
        burst_capacity=3,
        fields=[sample_field, sample_price_field],
        holdout_urls=[
            "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
            "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html",
            "https://books.toscrape.com/catalogue/soumission_998/index.html",
        ],
        posture=ScrapingPosture.STRICT_COMPLIANCE,
    )


@pytest.fixture
def sample_lkg_snapshot():
    """An LKGSnapshot matching the actual Pydantic model."""
    return LKGSnapshot(
        domain="books.toscrape.com",
        field_name="title",
        selector="h1",
        strategy=SelectorStrategy.CSS,
        ax_tree_neighborhood='- heading "A Light in the Attic" [level=1]',
        text_signature="A Light in the Attic",
        sample_value="A Light in the Attic",
        page_url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        snapshot_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_extraction_result():
    """A successful ExtractionResult matching the actual Pydantic model."""
    return ExtractionResult(
        field_name="title",
        value="A Light in the Attic",
        selector_used="h1",
        strategy=SelectorStrategy.CSS,
        page_url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        success=True,
    )


@pytest.fixture
def sample_failed_extraction():
    """A failed ExtractionResult for drift testing."""
    return ExtractionResult(
        field_name="title",
        value=None,
        selector_used="h1",
        strategy=SelectorStrategy.CSS,
        page_url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        success=False,
        error="Timeout: locator.text_content()",
    )


@pytest.fixture
def sample_business_rules():
    """BusinessRulesConfig with test rules matching actual model."""
    return BusinessRulesConfig(
        rules=[
            BusinessRule(
                field="price",
                op="gt",
                value=0,
                context={"product_type": "physical"},
                description="Physical product prices must be positive",
            ),
            BusinessRule(
                field="title",
                op="min_length",
                value=1,
                description="Title must not be empty",
            ),
            BusinessRule(
                field="title",
                op="max_length",
                value=500,
                description="Title must be under 500 characters",
            ),
        ]
    )


@pytest.fixture
def sample_volatility_profiles():
    """VolatilityProfilesConfig matching actual model."""
    return VolatilityProfilesConfig(
        profiles={
            "low": VolatilityProfileConfig(
                description="Stable fields",
                sigma_threshold=2.0,
            ),
            "medium": VolatilityProfileConfig(
                description="Moderate variance",
                sigma_threshold=3.0,
            ),
            "high": VolatilityProfileConfig(
                description="High variance",
                sigma_threshold=5.0,
            ),
        }
    )


@pytest.fixture
def mock_redis():
    """Fake async Redis for testing without a real Redis server."""
    return fakeredis.aioredis.FakeRedis()
