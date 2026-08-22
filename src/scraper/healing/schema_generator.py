"""
Auto-Schema Generator for arbitrary URLs using Google Gemini.

Inspects an unvisited webpage's accessibility tree, infers the relevant data fields
or uses a user-provided description, and synthesizes a production-grade DomainConfig YAML.
"""

import os
import re
from typing import Optional, List
from urllib.parse import urlparse
import yaml
import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from scraper.core.models import DomainConfig, FieldDefinition
from scraper.core.enums import SelectorStrategy, ScrapingPosture, VolatilityProfile

logger = structlog.get_logger(__name__)


class InferredField(BaseModel):
    name: str = Field(description="Normalized snake_case field name, e.g. title, price, rating, review_count, product_url")
    selector: str = Field(description="Playwright CSS or text selector (relative to item card if multi_item is True)")
    strategy: str = Field(default="css", description="Selector strategy: css, text, role, or xpath")
    field_type: str = Field(default="string", description="Type: string, float, int, date, or url")
    description: str = Field(description="Brief explanation of the field")


class InferredSchema(BaseModel):
    multi_item: bool = Field(
        default=False,
        description="True if this page is a product listing, catalog, search results, or storefront containing multiple repeated items/cards; False if it is a single-entity page (e.g. single product details)",
    )
    item_container: Optional[str] = Field(
        default=None,
        description="CSS selector for the repeating item card container when multi_item is True (e.g. '[role=\"group\"] > [role=\"listitem\"]', '[role=\"listitem\"]', '.s-result-item', '.product-card', 'li')",
    )
    scroll_count: int = Field(
        default=0,
        description="Recommended number of scroll steps (e.g. 8-12) to trigger lazy-loaded carousels or infinite scroll, or 0 if static",
    )
    fields: List[InferredField] = Field(description="List of detected data fields (relative to item container if multi_item)")
    rate_limit_rpm: int = Field(default=30, description="Recommended safe requests per minute")


class AutoSchemaGenerator:
    """
    Synthesizes domain configuration schemas for arbitrary URLs automatically.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required for auto-schema generation.")
        self.client = genai.Client(api_key=self.api_key)

    async def generate_schema(
        self,
        url: str,
        ax_tree: str,
        user_prompt: Optional[str] = None,
    ) -> DomainConfig:
        domain = urlparse(url).netloc.replace("www.", "")
        
        prompt = f"""[System: You are an expert data architect. Analyze this webpage's Accessibility Tree (AXTree) snapshot and generate a resilient, high-precision extraction schema for the core data on the page.]

Target URL: {url}
Target Domain: {domain}
User Request / Focus Fields: {user_prompt or "Extract all primary entity fields (e.g. title/name, price/cost, description, rating, review count, product URL)"}

Accessibility Tree Snapshot:
<untrusted_scraped_content>
{ax_tree[:10000]}
</untrusted_scraped_content>

CRITICAL INSTRUCTIONS:
1. Determine if this is a MULTI-ITEM listing page (e.g., storefront, search results, category catalog with multiple products/items) or a SINGLE-ITEM page (e.g. a single product/article page).
2. If MULTI-ITEM:
   - Set multi_item = true.
   - Specify item_container (e.g. '[role="group"] > [role="listitem"]', '[role="listitem"]', '.s-result-item', 'li').
   - Set scroll_count = 10 if the page uses lazy-loading carousels or infinite scrolling.
   - Field selectors MUST be relative to the item container card (e.g., 'a[href*="/dp/"]' for title/URL, '.a-price' or specific text patterns for price/rating).
3. If SINGLE-ITEM:
   - Set multi_item = false, item_container = null, scroll_count = 0.
   - Field selectors should be page-level selectors.
4. For URLs/links, set field_type = "url" (the extraction engine will automatically pull the href attribute).
5. For prices/numbers/ratings, choose appropriate field_types ("string", "float", "int", "url").
"""
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        
        response = self.client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=InferredSchema,
                temperature=0.1,
            ),
        )

        if hasattr(response, "parsed") and response.parsed:
            schema_data = response.parsed
        else:
            schema_data = InferredSchema.model_validate_json(response.text)

        field_defs = []
        for f in schema_data.fields:
            # Map strategy
            strat = SelectorStrategy.CSS
            if f.strategy.lower() == "text":
                strat = SelectorStrategy.TEXT
            elif f.strategy.lower() == "role":
                strat = SelectorStrategy.ROLE
            elif f.strategy.lower() == "xpath":
                strat = SelectorStrategy.XPATH

            field_defs.append(
                FieldDefinition(
                    name=re.sub(r'[^a-z0-9_]', '_', f.name.lower()),
                    selector=f.selector,
                    strategy=strat,
                    field_type=f.field_type.lower(),
                    volatility=VolatilityProfile.LOW,
                    required=True if f.name in ("title", "name", "price", "product_title") else False,
                    description=f.description,
                )
            )

        domain_config = DomainConfig(
            domain=domain,
            rate_limit_rpm=schema_data.rate_limit_rpm,
            burst_capacity=5,
            fields=field_defs,
            holdout_urls=[url],
            posture=ScrapingPosture.STRICT_COMPLIANCE,
            multi_item=schema_data.multi_item,
            item_container=schema_data.item_container,
            scroll_count=schema_data.scroll_count,
        )

        return domain_config

    def save_config(self, config: DomainConfig, config_dir: str = "config") -> str:
        """
        Saves the DomainConfig to config/domains/<domain>.yaml.
        """
        domains_dir = os.path.join(config_dir, "domains")
        os.makedirs(domains_dir, exist_ok=True)
        
        safe_domain = config.domain.replace(".", "_") + ".yaml"
        file_path = os.path.join(domains_dir, safe_domain)

        data = {
            "domain": config.domain,
            "multi_item": config.multi_item,
            "item_container": config.item_container,
            "scroll_count": config.scroll_count,
            "rate_limit": {
                "requests_per_minute": config.rate_limit_rpm,
                "burst_capacity": config.burst_capacity,
            },
            "fields": [
                {
                    "name": f.name,
                    "selector": f.selector,
                    "strategy": f.strategy.value,
                    "field_type": f.field_type,
                    "volatility": f.volatility.value,
                    "required": f.required,
                    "description": f.description,
                }
                for f in config.fields
            ],
            "holdout_urls": config.holdout_urls,
        }

        with open(file_path, "w", encoding="utf-8") as out:
            yaml.dump(data, out, sort_keys=False)

        logger.info("saved_domain_config", path=file_path, domain=config.domain)
        return file_path
