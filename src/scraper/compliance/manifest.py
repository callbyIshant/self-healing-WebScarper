"""
Legal Manifest loader and validator.
"""

import os
import json
import hmac
import hashlib
import structlog
from datetime import datetime, timedelta
from typing import Dict, Tuple

from scraper.core.models import LegalManifest
from scraper.core.exceptions import ManifestUnreadableError

logger = structlog.get_logger()

class LegalManifestLoader:
    def __init__(self, manifests_dir: str = "config/manifests", cache_ttl_minutes: int = 60):
        self.manifests_dir = manifests_dir
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self.cache: Dict[str, Tuple[LegalManifest, datetime]] = {}
        self.signing_key = os.environ.get("MANIFEST_SIGNING_KEY", "").encode("utf-8")

    async def load_manifest(self, domain: str) -> LegalManifest:
        """
        Loads manifest JSON files from disk, validates signature, and caches with TTL.
        """
        if domain in self.cache:
            manifest, timestamp = self.cache[domain]
            if datetime.now() - timestamp < self.cache_ttl:
                return manifest

        manifest_path = os.path.join(self.manifests_dir, f"{domain}.json")
        if not os.path.exists(manifest_path):
            raise ManifestUnreadableError(f"Manifest file missing for {domain}")

        try:
            with open(manifest_path, "r") as f:
                data = json.load(f)

            signature = data.pop("signature", None)
            if not signature or not self.verify_signature(data, signature):
                raise ManifestUnreadableError(f"Invalid signature for {domain} manifest")
            
            # Using pydantic parsing if LegalManifest is a pydantic model
            if hasattr(LegalManifest, "model_validate"):
                manifest = LegalManifest.model_validate(data)
            elif hasattr(LegalManifest, "parse_obj"):
                manifest = LegalManifest.parse_obj(data)
            else:
                manifest = LegalManifest(**data)
                
            self.cache[domain] = (manifest, datetime.now())
            return manifest
            
        except ManifestUnreadableError:
            raise
        except Exception as e:
            logger.error("Failed to load manifest", domain=domain, error=str(e))
            raise ManifestUnreadableError(f"Failed to read manifest for {domain}: {str(e)}")

    def verify_signature(self, manifest_data: dict, signature: str) -> bool:
        """
        Validates HMAC-SHA256 signature against env var MANIFEST_SIGNING_KEY.
        """
        if not self.signing_key:
            logger.warning("MANIFEST_SIGNING_KEY not set, signature validation will fail")
            return False
            
        message = json.dumps(manifest_data, sort_keys=True).encode("utf-8")
        expected_signature = hmac.new(self.signing_key, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_signature, signature)
