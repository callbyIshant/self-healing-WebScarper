"""
Compliance Gate layer for validating domain postures and legal manifests.
"""

import os
import structlog
from datetime import datetime, timezone
from typing import Dict
import yaml

from scraper.core.enums import ScrapingPosture
from scraper.core.exceptions import ManifestUnreadableError, WAFBlockedError

from .manifest import LegalManifestLoader

logger = structlog.get_logger()

class ComplianceGate:
    def __init__(self, manifest_loader: LegalManifestLoader, config_path: str = "config/scraping_postures.yaml"):
        self.manifest_loader = manifest_loader
        self.config_path = config_path
        self.domain_postures: Dict[str, ScrapingPosture] = {}
        self._load_config()

    def _load_config(self) -> None:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    data = yaml.safe_load(f)
                    for domain, posture_str in data.get("postures", {}).items():
                        self.domain_postures[domain] = ScrapingPosture(posture_str)
        except Exception as e:
            logger.error("Failed to load scraping postures", error=str(e))

    async def check_compliance(self, domain: str, url: str) -> ScrapingPosture:
        """
        Check compliance for a given domain and URL.
        """
        posture = self.domain_postures.get(domain, ScrapingPosture.STRICT_COMPLIANCE)
        
        if posture == ScrapingPosture.ADVERSARIAL_COMMERCIAL:
            try:
                manifest = await self.manifest_loader.load_manifest(domain)
                
                # Expiration check: evaluated on every call
                if manifest.expiration_date.tzinfo is None:
                    manifest_expiry = manifest.expiration_date.replace(tzinfo=timezone.utc)
                else:
                    manifest_expiry = manifest.expiration_date
                    
                if datetime.now(timezone.utc) > manifest_expiry:
                    logger.warning("Manifest expired, defaulting to STRICT_COMPLIANCE", domain=domain)
                    return ScrapingPosture.STRICT_COMPLIANCE
                    
            except ManifestUnreadableError as e:
                logger.error("Manifest unreadable, defaulting to STRICT_COMPLIANCE", domain=domain, error=str(e))
                return ScrapingPosture.STRICT_COMPLIANCE
            except Exception as e:
                logger.error("Unexpected error loading manifest, defaulting to STRICT_COMPLIANCE", domain=domain, error=str(e))
                return ScrapingPosture.STRICT_COMPLIANCE
                
        return posture

    def check_response_compliance(self, domain: str, status_code: int, url: str) -> None:
        """
        Check if a response indicates a WAF block or hard stop under STRICT_COMPLIANCE.
        Raises WAFBlockedError if blocked.
        """
        posture = self.domain_postures.get(domain, ScrapingPosture.STRICT_COMPLIANCE)
        if posture == ScrapingPosture.STRICT_COMPLIANCE:
            if status_code in (403, 429) or (400 <= status_code < 500 and status_code != 404):
                logger.warning("WAF or hard block detected under STRICT_COMPLIANCE", domain=domain, status_code=status_code)
                raise WAFBlockedError(f"Blocked by WAF, CAPTCHA, or Hard Stop on {domain} (Status: {status_code})")
