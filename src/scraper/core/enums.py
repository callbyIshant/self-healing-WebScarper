"""Enumerations for state machines, postures, and classification types."""

from enum import Enum, auto


class ScrapingPosture(str, Enum):
    """Legal compliance posture per target domain (§4.1).

    STRICT_COMPLIANCE: Honor robots.txt, treat WAF/403/CAPTCHA as hard stops.
    ADVERSARIAL_COMMERCIAL: Requires signed legal manifest; allows advanced techniques.
    """

    STRICT_COMPLIANCE = "strict_compliance"
    ADVERSARIAL_COMMERCIAL = "adversarial_commercial"


class BreakerState(str, Enum):
    """Circuit breaker state machine states (§4.5).

    CLOSED: Normal operation, failures increment counter.
    OPEN: Tripped — fail fast, bypass scraping/healing.
    HALF_OPEN: Canary probe permitted (spatial breaker only).
    REQUIRES_HUMAN_INTERVENTION: Locked — only human reset clears this.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    REQUIRES_HUMAN_INTERVENTION = "requires_human_intervention"


class DriftType(str, Enum):
    """Classification of detected drift (§4.5)."""

    LOCAL = "local"  # Single field failure — proceed to Tier 3
    GLOBAL = "global"  # >40% fields fail — halt domain, page human


class VolatilityProfile(str, Enum):
    """Statistical anomaly volatility classification per field (§4.4.3)."""

    LOW = "low"  # Stable fields (dimensions, categories): 2σ threshold
    MEDIUM = "medium"  # Moderate variance (prices, ratings): 3σ threshold
    HIGH = "high"  # High variance (stock, availability): 5σ threshold


class SelectorStrategy(str, Enum):
    """Locator strategy type, ordered by preference (§4.3)."""

    ROLE = "role"  # Playwright get_by_role — most resilient
    ARIA = "aria"  # ARIA labels / data attributes
    TEXT = "text"  # Text content matching
    TEST_ID = "test_id"  # data-testid attributes
    CSS = "css"  # CSS selectors — fragile
    XPATH = "xpath"  # XPath — most fragile


class ValidationCheckType(str, Enum):
    """Ordered validation check types (§4.4)."""

    TYPE = "type"  # Generic type/format validation
    BUSINESS_RULE = "business_rule"  # Domain-specific rules
    STATISTICAL = "statistical"  # Rolling distribution anomaly detection


class HealingOutcome(str, Enum):
    """Result of a self-healing attempt."""

    AUTO_APPROVED = "auto_approved"  # Confidence above threshold, hot-reloaded
    QUARANTINED = "quarantined"  # Below threshold, field nulled
    REJECTED_OVERFIT = "rejected_overfit"  # Cross-validation failed
    REJECTED_BREAKER = "rejected_breaker"  # Circuit breaker blocked healing
    FAILED = "failed"  # Agent could not produce a valid repair


class PipelineStage(str, Enum):
    """Stages in the end-to-end execution flow (§7)."""

    COMPLIANCE_CHECK = "compliance_check"
    TOKEN_ACQUISITION = "token_acquisition"
    EXTRACTION = "extraction"
    TYPE_VALIDATION = "type_validation"
    BUSINESS_VALIDATION = "business_validation"
    STATISTICAL_VALIDATION = "statistical_validation"
    SPATIAL_BREAKER_CHECK = "spatial_breaker_check"
    TEMPORAL_BREAKER_CHECK = "temporal_breaker_check"
    SANITIZATION = "sanitization"
    HEALING = "healing"
    CROSS_VALIDATION = "cross_validation"
    CONFIDENCE_GATE = "confidence_gate"
    QUARANTINE = "quarantine"
    EMISSION = "emission"
