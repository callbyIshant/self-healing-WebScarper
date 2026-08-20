"""
Locator Registry module for managing active locators per domain and field.
"""
import asyncio
from typing import Dict, Tuple

import structlog

from scraper.core.enums import SelectorStrategy
from scraper.core.models import DomainConfig

logger = structlog.get_logger(__name__)


class LocatorRegistry:
    """
    In-memory registry of active locators per domain/field.
    """
    def __init__(self) -> None:
        # dict mapping domain -> dict mapping field_name -> (selector, strategy)
        self._registry: Dict[str, Dict[str, Tuple[str, SelectorStrategy]]] = {}
        self._lock = asyncio.Lock()

    def get_locator(self, domain: str, field_name: str) -> Tuple[str, SelectorStrategy]:
        """
        Get the current locator for a given domain and field.
        """
        domain_locators = self._registry.get(domain, {})
        if field_name not in domain_locators:
            raise KeyError(f"Locator not found for field {field_name} on domain {domain}")
        return domain_locators[field_name]

    async def update_locator(self, domain: str, field_name: str, new_selector: str, strategy: SelectorStrategy) -> None:
        """
        Hot-reload a locator without restart.
        """
        async with self._lock:
            if domain not in self._registry:
                self._registry[domain] = {}
            self._registry[domain][field_name] = (new_selector, strategy)
            logger.info("updated_locator", domain=domain, field_name=field_name, strategy=strategy.value)

    def get_all_locators(self, domain: str) -> Dict[str, Tuple[str, SelectorStrategy]]:
        """
        Get all locators for a domain.
        """
        return self._registry.get(domain, {}).copy()

    def load_from_config(self, config: DomainConfig) -> None:
        """
        Load locators from a DomainConfig.
        Prioritizes strategies implicitly based on the order defined or explicitly.
        """
        domain = config.domain
        if domain not in self._registry:
            self._registry[domain] = {}
            
        for field in config.fields:
            self._registry[domain][field.name] = (field.selector, field.strategy)
            logger.debug("loaded_locator_from_config", domain=domain, field_name=field.name)
