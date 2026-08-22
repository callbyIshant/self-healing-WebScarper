"""
Data Plane (Layer 3) - Deterministic Extraction.
"""
import re
from typing import Any, List, Optional
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
                ax_tree_neighborhood = await locator.first.aria_snapshot()
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

    # ──────────────────────────────────────────────
    # Multi-Item Extraction (Listing Pages)
    # ──────────────────────────────────────────────

    async def scroll_to_load(
        self, page: Page, scroll_count: int = 10, delay_ms: int = 800
    ) -> None:
        """Scroll the page incrementally to trigger lazy-loaded content."""
        if scroll_count <= 0:
            return
        logger.info("scroll_to_load", steps=scroll_count)
        for i in range(scroll_count):
            await page.evaluate(f"window.scrollTo(0, {(i + 1) * 600})")
            await page.wait_for_timeout(delay_ms)
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

    async def extract_page_items(
        self, page: Page, domain_config: DomainConfig
    ) -> tuple[List[dict[str, Any]], List[ExtractionResult], dict[str, bool]]:
        """
        Universal multi-item extraction for listing/catalog pages.

        Iterates over matching `item_container` elements and extracts
        each configured field relative to that container. Supports relative
        URL resolution, generic container fallbacks, and deduplication.
        """
        from urllib.parse import urljoin

        domain = domain_config.domain
        container_sel = domain_config.item_container

        items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        field_success: dict[str, bool] = {f.name: False for f in domain_config.fields}
        sample_results: list[ExtractionResult] = []

        # Find all matching containers
        containers = page.locator(container_sel) if container_sel else None
        count = await containers.count() if containers else 0

        # Fallback container candidates if initial selector found nothing
        if count == 0:
            fallbacks = [
                '[role="listitem"]',
                'article',
                'li:has(a[href])',
                'li',
                '[class*="card"]',
                '[class*="item"]',
                '[class*="result"]',
                '[class*="product"]',
                '[class*="listing"]',
            ]
            for fb in fallbacks:
                try:
                    fb_loc = page.locator(fb)
                    fb_count = await fb_loc.count()
                    if fb_count > 0:
                        logger.info("using_fallback_container", domain=domain, selector=fb, count=fb_count)
                        containers = fb_loc
                        count = fb_count
                        break
                except Exception:
                    continue

        logger.info("multi_item_containers", domain=domain, selector=container_sel, count=count)

        if not containers or count == 0:
            return [], [], field_success

        for idx in range(count):
            container = containers.nth(idx)
            item: dict[str, Any] = {}
            is_first = len(items) == 0

            # Get container full text once for pattern matching
            container_text = ""
            try:
                container_text = await container.text_content(timeout=1000) or ""
            except Exception:
                pass

            for field in domain_config.fields:
                try:
                    selector, strategy = self.registry.get_locator(domain, field.name)
                except KeyError:
                    selector, strategy = field.selector, field.strategy

                value = None
                fname = field.name.lower()

                # Strategy 1: Scoped CSS/text locator
                if selector and selector != "text":
                    try:
                        scoped = container.locator(selector)
                        if await scoped.count() > 0:
                            if field.field_type == "url" or "url" in fname:
                                href = await scoped.first.get_attribute("href", timeout=1000)
                                if href:
                                    value = urljoin(page.url, href)
                            else:
                                text = await scoped.first.text_content(timeout=1000)
                                if text and text.strip():
                                    value = text.strip()
                    except Exception:
                        pass

                # Strategy 2: URL field extraction fallback
                if value is None and (field.field_type == "url" or "url" in fname):
                    try:
                        link = container.locator('a[href]')
                        if await link.count() > 0:
                            href = await link.first.get_attribute("href", timeout=1000)
                            if href:
                                value = urljoin(page.url, href)
                    except Exception:
                        pass

                # Strategy 3: Generic regex pattern heuristics from container text
                if value is None and container_text:
                    if "price" in fname or field.field_type in ("float", "price"):
                        m = re.search(r'([$₹€£¥]\s*[\d,]+\.?\d*)', container_text)
                        if m:
                            value = m.group(1).strip()
                    elif "rating" in fname or "star" in fname:
                        m = re.search(r'([0-5]\.\d)\s*(?:out of 5 stars|stars|\/5)', container_text, re.IGNORECASE)
                        if m:
                            value = m.group(1).strip() + " out of 5 stars"
                    elif "review" in fname or "count" in fname:
                        m = re.search(r'([\d,]+)\s*(?:customer reviews?|reviews?|ratings?)', container_text, re.IGNORECASE)
                        if m:
                            value = m.group(1).strip()
                    elif ("title" in fname or "name" in fname):
                        link = container.locator('a[href]')
                        if await link.count() > 0:
                            aria = await link.first.get_attribute("aria-label", timeout=500)
                            if aria and aria.strip():
                                value = aria.strip()
                        if not value and container_text.strip():
                            value = container_text.strip().split("\n")[0]

                item[field.name] = value
                if value is not None:
                    field_success[field.name] = True

                # Build sample ExtractionResult for first container (for pipeline LKG/drift)
                if is_first:
                    sample_results.append(ExtractionResult(
                        field_name=field.name,
                        value=value,
                        selector_used=selector,
                        strategy=strategy,
                        page_url=page.url,
                        success=value is not None,
                        error=None if value is not None else f"No match in container #{idx}",
                    ))

            # Domain-agnostic deduplication (prefer URL field, then title/name, then primary field)
            dedup_key = None
            for field in domain_config.fields:
                if (field.field_type == "url" or "url" in field.name.lower()) and item.get(field.name):
                    dedup_key = str(item[field.name]).split("?")[0]  # Normalize URL without query noise
                    break

            if not dedup_key:
                for field in domain_config.fields:
                    if item.get(field.name):
                        dedup_key = str(item[field.name])[:100].strip()
                        break

            # Skip empty items where all extracted values are None
            if not dedup_key or all(v is None for v in item.values()):
                continue

            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            items.append(item)

        logger.info(
            "multi_item_extracted",
            domain=domain,
            total_containers=count,
            unique_items=len(items),
            field_success={k: v for k, v in field_success.items()},
        )

        return items, sample_results, field_success

    async def capture_aria_snapshot(self, page: Page, scope_selector: Optional[str] = None) -> str:
        """
        Capture ARIA snapshot for drift analysis.
        """
        if scope_selector:
            return await page.locator(scope_selector).aria_snapshot()
        return await page.locator("body").aria_snapshot()

