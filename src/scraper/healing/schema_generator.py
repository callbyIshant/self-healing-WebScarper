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
    name: str = Field(description="Normalized snake_case field name, e.g. title, price, rating")
    selector: str = Field(description="Playwright CSS or text selector")
    strategy: str = Field(default="css", description="Selector strategy: css, text, role, or xpath")
    field_type: str = Field(default="string", description="Type: string, float, int, date, or url")
    description: str = Field(description="Brief explanation of the field")


class InferredSchema(BaseModel):
    fields: List[InferredField] = Field(description="List of detected data fields")
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
User Request / Focus Fields: {user_prompt or "Extract all primary entity fields (e.g. title/name, price/cost, description, rating, author/company, date)"}

Accessibility Tree Snapshot:
<untrusted_scraped_content>
{ax_tree[:8000]}
</untrusted_scraped_content>

Generate a clean list of fields with reliable CSS or Playwright text selectors (e.g. 'h1', '.price', 'text=/.../').
"""
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        
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
                    required=True if f.name in ("title", "name", "price") else False,
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
