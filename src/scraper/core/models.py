"""Pydantic data contracts shared across all pipeline layers.

Every model here is a data transfer object — no business logic, no I/O.
Layers import these for type safety and structured LLM output enforcement.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from scraper.core.enums import (
    BreakerState,
    DriftType,
    HealingOutcome,
    ScrapingPosture,
    SelectorStrategy,
    ValidationCheckType,
    VolatilityProfile,
)


# ──────────────────────────────────────────────
# Configuration Models
# ──────────────────────────────────────────────


class FieldDefinition(BaseModel):
    """Schema for a single extractable field within a domain config."""

    name: str
    selector: str
    strategy: SelectorStrategy = SelectorStrategy.CSS
    field_type: Literal["string", "float", "int", "bool", "date", "url"] = "string"
    volatility: VolatilityProfile = VolatilityProfile.MEDIUM
    required: bool = True
    description: str = ""


class DomainConfig(BaseModel):
    """Per-domain extraction configuration loaded from config/domains/*.yaml."""

    domain: str
    rate_limit_rpm: int = Field(default=30, ge=1, description="Requests per minute")
    burst_capacity: int = Field(default=5, ge=1)
    fields: list[FieldDefinition] = Field(default_factory=list)
    holdout_urls: list[str] = Field(default_factory=list, min_length=0)
    posture: ScrapingPosture = ScrapingPosture.STRICT_COMPLIANCE
    manifest_path: Optional[str] = None
    multi_item: bool = Field(
        default=False,
        description="True for listing pages (search results, storefronts) with multiple repeated entities",
    )
    item_container: Optional[str] = Field(
        default=None,
        description="CSS selector for the repeating item card container (required when multi_item=True)",
    )
    scroll_count: int = Field(
        default=0,
        ge=0,
        description="Number of scroll steps to trigger lazy-loading (0 = no scrolling)",
    )


class BusinessRule(BaseModel):
    """A single business validation rule (§4.4.2)."""

    field: str
    op: Literal["gt", "gte", "lt", "lte", "eq", "ne", "min_length", "max_length", "regex", "in"]
    value: Any
    context: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class BusinessRulesConfig(BaseModel):
    """Collection of business rules loaded from config/business_rules.yaml."""

    rules: list[BusinessRule] = Field(default_factory=list)


class VolatilityProfileConfig(BaseModel):
    """Threshold configuration for a volatility profile."""

    description: str = ""
    sigma_threshold: float = 3.0


class VolatilityProfilesConfig(BaseModel):
    """All volatility profiles loaded from config/volatility_profiles.yaml."""

    profiles: dict[str, VolatilityProfileConfig] = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Legal & Compliance Models (§4.1)
# ──────────────────────────────────────────────


class LegalManifest(BaseModel):
    """Signed legal clearance manifest for adversarial/commercial scraping."""

    legal_approver: str = Field(min_length=1)
    expiration_date: datetime
    authorized_domains: list[str] = Field(min_length=1)
    authorized_techniques: list[str] = Field(default_factory=list)
    signature: str = Field(min_length=1, description="HMAC-SHA256 signature")
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expiration_date

    def covers_domain(self, domain: str) -> bool:
        return any(
            domain == d or domain.endswith(f".{d}") for d in self.authorized_domains
        )


# ──────────────────────────────────────────────
# Extraction Models (§4.3)
# ──────────────────────────────────────────────


class ExtractionResult(BaseModel):
    """Result of extracting a single field from a page."""

    field_name: str
    value: Any
    selector_used: str
    strategy: SelectorStrategy
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    page_url: str = ""
    success: bool = True
    error: Optional[str] = None


class LKGSnapshot(BaseModel):
    """Last Known Good snapshot for a selector (§4.3).

    Stored in a sliding window of 5 per selector.
    """

    domain: str
    field_name: str
    selector: str
    strategy: SelectorStrategy
    ax_tree_neighborhood: str = Field(
        description="Parent + sibling ARIA context of the target node"
    )
    text_signature: str = Field(description="Normalized text content of the target node")
    sample_value: Any = None
    snapshot_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    page_url: str = ""


# ──────────────────────────────────────────────
# Validation Models (§4.4)
# ──────────────────────────────────────────────


class ValidationResult(BaseModel):
    """Result of a single validation check on a field."""

    field_name: str
    check_type: ValidationCheckType
    passed: bool
    failure_reason: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────
# Self-Healing Models (§4.6)
# ──────────────────────────────────────────────


class SelectorRepairResult(BaseModel):
    """Structured output from the LLM healing agent (§4.6).

    This is the Pydantic schema enforced on LLM structured output.
    The confidence_score here is the LLM's raw proposal; the actual
    confidence used for gating is computed deterministically by
    similarity.py against the LKG baseline.
    """

    field_name: str = Field(description="Name of the field being repaired")
    primary_selector: str = Field(
        description="Proposed repaired selector (Playwright locator syntax)"
    )
    selector_strategy: SelectorStrategy = Field(
        description="Type of locator strategy"
    )
    role_name: Optional[str] = Field(
        default=None, description="Accessible name if strategy is role"
    )
    role_type: Optional[str] = Field(
        default=None, description="ARIA role type (heading, button, link, etc.)"
    )
    fallback_selectors: list[str] = Field(
        default_factory=list, description="Alternative selector candidates"
    )
    repair_reasoning: str = Field(
        description="Explanation of what changed in the DOM and why this selector should work"
    )


# ──────────────────────────────────────────────
# Circuit Breaker Models (§4.5)
# ──────────────────────────────────────────────


class CircuitBreakerRecord(BaseModel):
    """Persisted state of a circuit breaker."""

    domain: str
    breaker_type: Literal["spatial", "temporal"]
    field_name: Optional[str] = None  # None for spatial (domain-level)
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    last_failure_at: Optional[datetime] = None
    last_state_change_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    reset_by: Optional[str] = None  # Human who reset it
    reset_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Quarantine Models (§4.8)
# ──────────────────────────────────────────────


class QuarantineRecord(BaseModel):
    """A quarantined extraction with snapshot for later replay (§4.8).

    The snapshot_id is generated exactly once at quarantine time
    and is never regenerated on retry.
    """

    snapshot_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique ID generated once at quarantine time — never regenerated",
    )
    domain: str
    field_name: str
    page_url: str
    broken_selector: str
    sanitized_ax_tree: str
    proposed_selector: Optional[str] = None
    confidence_score: Optional[float] = None
    quarantined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    retention_expires_at: Optional[datetime] = None
    resolved: bool = False
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None


# ──────────────────────────────────────────────
# Drift & Telemetry Event Models (§4.9)
# ──────────────────────────────────────────────


class DriftEvent(BaseModel):
    """Record of a detected drift event."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: str
    field_name: str
    drift_type: DriftType
    old_selector: str
    new_selector: Optional[str] = None
    confidence_score: Optional[float] = None
    outcome: HealingOutcome = HealingOutcome.FAILED
    time_to_heal_seconds: Optional[float] = None
    auto_healed: bool = False
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Pipeline I/O Models
# ──────────────────────────────────────────────


class ScrapingRequest(BaseModel):
    """Input to the pipeline — a request to scrape a specific page."""

    url: str
    domain: str
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    priority: int = Field(default=0, ge=0)


class ScrapingResponse(BaseModel):
    """Output of the pipeline — extracted data with metadata."""

    request_id: str
    url: str
    domain: str
    fields: dict[str, Any] = Field(default_factory=dict)
    items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of extracted item dicts for multi-item (listing) pages",
    )
    quarantined_fields: list[str] = Field(default_factory=list)
    extraction_results: list[ExtractionResult] = Field(default_factory=list)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    drift_events: list[DriftEvent] = Field(default_factory=list)
    success: bool = True
    error: Optional[str] = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
