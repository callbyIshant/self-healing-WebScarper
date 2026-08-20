"""Domain-specific exceptions for each pipeline layer.

Every layer raises its own exception type so that the pipeline orchestrator
can route failures to the correct recovery path. No layer catches another
layer's exceptions — the orchestrator is the only place where cross-layer
error handling occurs.
"""

from __future__ import annotations

from typing import Any, Optional


class ScraperError(Exception):
    """Base exception for all scraper errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


# ──────────────────────────────────────────────
# Layer 1 — Compliance Errors (§4.1)
# ──────────────────────────────────────────────


class ComplianceError(ScraperError):
    """A compliance check has failed — hard stop, no retry."""

    pass


class ManifestExpiredError(ComplianceError):
    """The legal clearance manifest for this domain has expired."""

    def __init__(self, domain: str, expiration_date: str) -> None:
        super().__init__(
            f"Legal manifest for '{domain}' expired at {expiration_date}",
            details={"domain": domain, "expiration_date": expiration_date},
        )


class ManifestUnreadableError(ComplianceError):
    """The manifest file cannot be read — default to STRICT_COMPLIANCE."""

    def __init__(self, domain: str, reason: str) -> None:
        super().__init__(
            f"Cannot read manifest for '{domain}': {reason}. Defaulting to STRICT_COMPLIANCE.",
            details={"domain": domain, "reason": reason},
        )


class RobotsTxtDisallowedError(ComplianceError):
    """The target URL is disallowed by robots.txt."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f"URL disallowed by robots.txt: {url}",
            details={"url": url},
        )


class WAFBlockedError(ComplianceError):
    """A WAF, CAPTCHA, or 403 was encountered under STRICT_COMPLIANCE."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(
            f"WAF/CAPTCHA/403 block on '{url}' (status {status_code}) — hard stop under STRICT_COMPLIANCE",
            details={"url": url, "status_code": status_code},
        )


# ──────────────────────────────────────────────
# Layer 2 — Rate Limiting Errors (§4.2)
# ──────────────────────────────────────────────


class RateLimitExceededError(ScraperError):
    """No token available — request must be requeued."""

    def __init__(self, domain: str, wait_seconds: float) -> None:
        super().__init__(
            f"Rate limit exceeded for '{domain}'. Retry in {wait_seconds:.1f}s",
            details={"domain": domain, "wait_seconds": wait_seconds},
        )


# ──────────────────────────────────────────────
# Layer 3 — Extraction Errors (§4.3)
# ──────────────────────────────────────────────


class ExtractionError(ScraperError):
    """A generic extraction failure."""

    pass


class SelectorBrokenError(ExtractionError):
    """A selector failed to locate the target element."""

    def __init__(self, domain: str, field_name: str, selector: str) -> None:
        super().__init__(
            f"Selector broken for '{field_name}' on '{domain}': {selector}",
            details={"domain": domain, "field_name": field_name, "selector": selector},
        )


# ──────────────────────────────────────────────
# Layer 4 — Validation Errors (§4.4)
# ──────────────────────────────────────────────


class FieldValidationError(ScraperError):
    """A field failed one of the three validation checks."""

    def __init__(
        self,
        field_name: str,
        check_type: str,
        reason: str,
        value: Any = None,
    ) -> None:
        super().__init__(
            f"Validation failed for '{field_name}' ({check_type}): {reason}",
            details={
                "field_name": field_name,
                "check_type": check_type,
                "reason": reason,
                "value": value,
            },
        )


# ──────────────────────────────────────────────
# Layer 5 — Circuit Breaker Errors (§4.5)
# ──────────────────────────────────────────────


class CircuitBreakerOpenError(ScraperError):
    """The circuit breaker is open — fail fast."""

    def __init__(self, domain: str, breaker_type: str) -> None:
        super().__init__(
            f"Circuit breaker OPEN for '{domain}' ({breaker_type})",
            details={"domain": domain, "breaker_type": breaker_type},
        )


class GlobalDriftError(ScraperError):
    """Global drift detected — too many fields broken, domain halted."""

    def __init__(self, domain: str, failed_ratio: float) -> None:
        super().__init__(
            f"Global drift on '{domain}': {failed_ratio:.0%} of fields failed. Domain halted.",
            details={"domain": domain, "failed_ratio": failed_ratio},
        )


class ThrashLimitError(ScraperError):
    """A field has exceeded its repair frequency — human intervention required."""

    def __init__(self, domain: str, field_name: str, repair_count: int, window_hours: int) -> None:
        super().__init__(
            f"Thrash limit hit for '{field_name}' on '{domain}': "
            f"{repair_count} repairs in {window_hours}h. Human intervention required.",
            details={
                "domain": domain,
                "field_name": field_name,
                "repair_count": repair_count,
                "window_hours": window_hours,
            },
        )


# ──────────────────────────────────────────────
# Layer 6 — Healing Errors (§4.6)
# ──────────────────────────────────────────────


class HealingError(ScraperError):
    """The self-healing agent failed to produce a valid repair."""

    pass


class SanitizationWarning(ScraperError):
    """Suspicious content detected during AXTree sanitization.

    This is a warning, not a block — the pipeline continues but
    logs the detection for monitoring.
    """

    def __init__(self, domain: str, pattern: str, context: str) -> None:
        super().__init__(
            f"Prompt injection pattern detected on '{domain}': '{pattern}'",
            details={"domain": domain, "pattern": pattern, "context": context},
        )


# ──────────────────────────────────────────────
# Layer 7 — Cross-Validation Errors (§4.7)
# ──────────────────────────────────────────────


class CrossValidationError(ScraperError):
    """The proposed selector failed cross-validation against holdout pages."""

    def __init__(
        self,
        domain: str,
        field_name: str,
        passed_count: int,
        total_count: int,
    ) -> None:
        super().__init__(
            f"Cross-validation failed for '{field_name}' on '{domain}': "
            f"passed {passed_count}/{total_count} holdout pages",
            details={
                "domain": domain,
                "field_name": field_name,
                "passed_count": passed_count,
                "total_count": total_count,
            },
        )


# ──────────────────────────────────────────────
# Security Errors
# ──────────────────────────────────────────────


class SSRFBlockedError(ScraperError):
    """A URL was blocked by the SSRF guard."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(
            f"SSRF blocked: '{url}' — {reason}",
            details={"url": url, "reason": reason},
        )


class SelectorInjectionError(ScraperError):
    """A proposed selector contains dangerous functions or patterns."""

    def __init__(self, selector: str, reason: str) -> None:
        super().__init__(
            f"Selector injection blocked: {reason}",
            details={"selector": selector, "reason": reason},
        )
