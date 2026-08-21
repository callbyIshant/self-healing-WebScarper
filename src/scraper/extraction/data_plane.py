"""
Data Plane (Layer 3) - Deterministic Extraction.
"""
from typing import List, Optional
from urllib.parse import urlparse

import structlog
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, Locator

from scraper.core.enums import SelectorStrategy
from scraper.core.models import (
    DomainConfig, ExtractionResult, FieldDefinition, LKGSnapshot
)
from scraper.extraction.locator_registry import LocatorRegistry
from scraper.extraction.lkg_store import LKGStore
from scraper.core.exceptions import ExtractionError

logger = structlog.get_logger(__name__)


class DataPlane:
    """
    Deterministic extraction engine (§4.3).
    No LLM calls, no external network calls.
    """
    def __init__(self, registry: LocatorRegistry, lkg_store: LKGStore) -> None:
        self.registry = registry
        self.lkg_store = lkg_store

    async def extract_page(self, page: Page, domain_config: DomainConfig) -> List[ExtractionResult]:
        """
        Execute deterministic extraction for all fields in the domain config.
        """
        results = []
        for field in domain_config.fields:
            # We pass domain by temporarily attaching it or we can resolve it directly
            result = await self.extract_field(page, field, domain=domain_config.domain)
            results.append(result)
        return results

    async def extract_field(self, page: Page, field: FieldDefinition, domain: str = "") -> ExtractionResult:
        """
        Execute deterministic extraction for a single field.
        """
        if not domain:
            domain = urlparse(page.url).netloc

        try:
            selector, strategy = self.registry.get_locator(domain, field.name)
        except KeyError:
            selector, strategy = field.selector, field.strategy

        page_url = page.url

        try:
            # Execute extraction using Playwright semantic APIs in priority order
            locator: Locator
            if selector.startswith("text=") or selector.startswith("xpath=") or selector.startswith("css="):
                locator = page.locator(selector)
            else:
                match strategy:
                    case SelectorStrategy.ROLE:
                        try:
                            locator = page.get_by_role(selector)  # type: ignore
                        except Exception:
                            locator = page.locator(selector)
                    case SelectorStrategy.ARIA:
                        locator = page.get_by_label(selector)
                    case SelectorStrategy.TEXT:
                        locator = page.locator(f"text={selector}")
                    case SelectorStrategy.TEST_ID:
                        locator = page.get_by_test_id(selector)
                    case _:
                        locator = page.locator(selector)
            
            # Fetch text content with 5-second timeout on first matching element
            text_content = await locator.first.text_content(timeout=5000)
            
            if text_content is None:
                raise ExtractionError(f"Field {field.name} found but returned None text_content")
                
            text_content = text_content.strip()

            result = ExtractionResult(
                field_name=field.name,
                value=text_content,
                selector_used=selector,
                strategy=strategy,
                page_url=page_url,
                success=True
            )

            # Best effort to capture AX tree context around the node
            ax_tree_neighborhood = ""
            try:
                ax_tree_neighborhood = await locator.aria_snapshot()
            except Exception:
                pass

            snapshot = LKGSnapshot(
                domain=domain,
                field_name=field.name,
                selector=selector,
                strategy=strategy,
                ax_tree_neighborhood=ax_tree_neighborhood,
                text_signature=text_content,
                sample_value=text_content,
                page_url=page_url
            )
            await self.lkg_store.push_snapshot(snapshot)

            return result

        except (PlaywrightTimeoutError, Exception) as e:
            logger.warning("extraction_failed", field=field.name, error=str(e), domain=domain)
            
            # On failure (timeout, element not found): capture ARIA snapshot via page.locator('body').aria_snapshot()
            try:
                await self.capture_aria_snapshot(page)
            except Exception as ax_e:
                logger.warning("failed_to_capture_aria", error=str(ax_e))

            return ExtractionResult(
                field_name=field.name,
                value=None,
                selector_used=selector,
                strategy=strategy,
                page_url=page_url,
                success=False,
                error=str(e)
            )

    async def capture_aria_snapshot(self, page: Page, scope_selector: Optional[str] = None) -> str:
        """
        Capture ARIA snapshot for drift analysis.
        """
        if scope_selector:
            return await page.locator(scope_selector).aria_snapshot()
        return await page.locator("body").aria_snapshot()
