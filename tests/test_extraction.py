import pytest
from unittest.mock import AsyncMock, MagicMock
from scraper.core.enums import SelectorStrategy, VolatilityProfile
from scraper.core.models import DomainConfig, FieldDefinition, ScrapingResponse
from scraper.extraction.data_plane import DataPlane
from scraper.extraction.locator_registry import LocatorRegistry
from scraper.extraction.lkg_store import LKGStore


@pytest.mark.asyncio
async def test_locator_registry_load_from_config(sample_domain_config):
    registry = LocatorRegistry()
    registry.load_from_config(sample_domain_config)
    selector, strategy = registry.get_locator(sample_domain_config.domain, "title")
    assert selector == "h1"
    assert strategy == SelectorStrategy.CSS


@pytest.mark.asyncio
async def test_locator_registry_hot_reload():
    registry = LocatorRegistry()
    await registry.update_locator("example.com", "title", ".new-title", SelectorStrategy.CSS)
    selector, strategy = registry.get_locator("example.com", "title")
    assert selector == ".new-title"
    assert strategy == SelectorStrategy.CSS


@pytest.mark.asyncio
async def test_multi_item_domain_config():
    config = DomainConfig(
        domain="amazon.com",
        multi_item=True,
        item_container='[role="listitem"]',
        scroll_count=10,
        fields=[
            FieldDefinition(
                name="title",
                selector='a[href*="/dp/"]',
                strategy=SelectorStrategy.CSS,
                field_type="string",
            ),
            FieldDefinition(
                name="price",
                selector='text',
                strategy=SelectorStrategy.CSS,
                field_type="string",
            ),
        ],
    )
    assert config.multi_item is True
    assert config.item_container == '[role="listitem"]'
    assert config.scroll_count == 10

    resp = ScrapingResponse(
        request_id="req-123",
        url="https://www.amazon.com/stores/page/123",
        domain="amazon.com",
        items=[
            {"title": "Product A", "price": "$29.99"},
            {"title": "Product B", "price": "$49.99"},
        ],
    )
    assert len(resp.items) == 2
    assert resp.items[0]["title"] == "Product A"


@pytest.mark.asyncio
async def test_extract_page_items_with_mock():
    registry = LocatorRegistry()
    lkg_store = LKGStore()
    data_plane = DataPlane(registry=registry, lkg_store=lkg_store)

    config = DomainConfig(
        domain="example.com",
        multi_item=True,
        item_container=".card",
        fields=[
            FieldDefinition(name="title", selector="h2", strategy=SelectorStrategy.CSS),
            FieldDefinition(name="price", selector=".price", strategy=SelectorStrategy.CSS),
        ],
    )

    # Mock Title Locator
    mock_title = MagicMock()
    mock_title.count = AsyncMock(return_value=1)
    mock_title_first = MagicMock()
    mock_title_first.text_content = AsyncMock(return_value="Running Shoes")
    mock_title.first = mock_title_first

    # Mock Price Locator
    mock_price = MagicMock()
    mock_price.count = AsyncMock(return_value=1)
    mock_price_first = MagicMock()
    mock_price_first.text_content = AsyncMock(return_value="$89.99")
    mock_price.first = mock_price_first

    # Mock Container
    mock_container = MagicMock()
    def container_locator(sel):
        if "h2" in sel:
            return mock_title
        elif "price" in sel:
            return mock_price
        empty = MagicMock()
        empty.count = AsyncMock(return_value=0)
        return empty

    mock_container.locator = MagicMock(side_effect=container_locator)
    mock_container.text_content = AsyncMock(return_value="Running Shoes $89.99")

    # Mock Containers list
    mock_containers = MagicMock()
    mock_containers.count = AsyncMock(return_value=1)
    mock_containers.nth = MagicMock(return_value=mock_container)

    # Mock Page
    mock_page = MagicMock()
    mock_page.url = "https://example.com/products"
    mock_page.locator = MagicMock(return_value=mock_containers)

    items, sample_results, field_success = await data_plane.extract_page_items(mock_page, config)

    assert len(items) == 1
    assert items[0]["title"] == "Running Shoes"
    assert items[0]["price"] == "$89.99"
    assert field_success["title"] is True
    assert field_success["price"] is True
