"""
Layer 1: Legal & Compliance Gate.
Responsible for ensuring that scraping operations adhere to domain-specific postures,
robots.txt directives, and legal clearance manifests.
"""

from .gate import ComplianceGate
from .manifest import LegalManifestLoader
from .robots import RobotsChecker

__all__ = ["ComplianceGate", "LegalManifestLoader", "RobotsChecker"]
