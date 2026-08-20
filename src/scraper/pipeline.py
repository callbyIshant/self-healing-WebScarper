"""End-to-end orchestrator for the self-healing web scraper (§7).

Wires all 9 layers together in the execution order defined in §7:
1. Acquire token + validate manifest (L2 + L1)
2. Execute deterministic extraction (L3)
3. On success → emit + update LKG
4. On failure → validate (L4) → spatial breaker (L5) → temporal breaker (L5)
   → sanitize + heal (L6) → cross-validate (L7) → confidence gate (L8)
5. Every event → telemetry (L9)
"""

from __future__ import annotations

import glob
import os
import time
from datetime import datetime, timezone
from typing import Any

import structlog
import yaml
from playwright.async_api import Browser, Playwright, async_playwright

from scraper.core.enums import (
    BreakerState,
    DriftType,
    HealingOutcome,
    SelectorStrategy,
    VolatilityProfile,
)
from scraper.core.exceptions import (
    CircuitBreakerOpenError,
    ComplianceError,
    CrossValidationError,
    GlobalDriftError,
    HealingError,
    RateLimitExceededError,
    ThrashLimitError,
)
from scraper.core.models import (
    BusinessRulesConfig,
    DomainConfig,
    DriftEvent,
    ExtractionResult,
    FieldDefinition,
    LKGSnapshot,
    QuarantineRecord,
    ScrapingRequest,
    ScrapingResponse,
    ValidationResult,
    VolatilityProfilesConfig,
)

# Layer 1 — Compliance
from scraper.compliance.gate import ComplianceGate
from scraper.compliance.robots import RobotsChecker
from scraper.compliance.manifest import LegalManifestLoader


# Layer 2 — Concurrency
from scraper.concurrency.rate_limiter import DistributedRateLimiter

# Layer 3 — Extraction
from scraper.extraction.data_plane import DataPlane
from scraper.extraction.lkg_store import LKGStore
from scraper.extraction.locator_registry import LocatorRegistry

# Layer 4 — Validation
from scraper.validation.pipeline import ValidationPipeline
from scraper.validation.type_validator import TypeValidator
from scraper.validation.business_rules import BusinessRuleValidator
from scraper.validation.statistical import StatisticalValidator

# Layer 5 — Circuit Breakers
from scraper.circuit_breaker.spatial import SpatialBreaker
from scraper.circuit_breaker.temporal import TemporalBreaker

# Layer 6 — Healing
from scraper.healing.agent import HealingAgent
from scraper.healing.sanitizer import AXTreeSanitizer
from scraper.healing.similarity import ConfidenceScorer

# Layer 7 — Cross-Validation
from scraper.cross_validation.holdout import CrossValidator

# Layer 8 — Confidence & Quarantine
from scraper.confidence.gate import ConfidenceGate
from scraper.confidence.quarantine import QuarantineStore

# Layer 9 — Telemetry
from scraper.telemetry.metrics import MetricsCollector
from scraper.telemetry.logger import setup_logging

# Storage
from scraper.storage.sqlite_store import SQLiteStore
from scraper.storage.redis_client import RedisClient
from scraper.storage.cold_storage import ColdStorage

# Security
from scraper.security.ssrf_guard import SSRFGuard
from scraper.security.pii_redactor import PIIRedactor

logger = structlog.get_logger()


class ScrapingPipeline:
    """Main pipeline orchestrator wiring all 9 layers."""

    def __init__(
        self,
        config_path: str = "config",
        db_path: str = "data/scraper.db",
        redis_url: str | None = None,
        cold_storage_path: str = "data/cold_storage",
        gemini_api_key: str | None = None,
    ) -> None:
        self.config_path = config_path
        self.db_path = db_path

        # Storage
        self.sqlite_store = SQLiteStore(db_path)
        self.redis_client = RedisClient(redis_url or "redis://localhost:6379/0")
        self.cold_storage = ColdStorage(cold_storage_path)

        # Domain configs
        self.domain_configs: dict[str, DomainConfig] = {}
        self.business_rules_config: BusinessRulesConfig | None = None
        self.volatility_config: VolatilityProfilesConfig | None = None

        # Layer instances (initialized in initialize())
        self.compliance_gate: ComplianceGate | None = None
        self.robots_checker: RobotsChecker | None = None
        self.rate_limiter: DistributedRateLimiter | None = None
        self.data_plane: DataPlane | None = None
        self.locator_registry: LocatorRegistry | None = None
        self.lkg_store: LKGStore | None = None
        self.validation_pipeline: ValidationPipeline | None = None
        self.spatial_breaker: SpatialBreaker | None = None
        self.temporal_breaker: TemporalBreaker | None = None
        self.healing_agent: HealingAgent | None = None
        self.sanitizer: AXTreeSanitizer | None = None
        self.scorer: ConfidenceScorer | None = None
        self.cross_validator: CrossValidator | None = None
        self.confidence_gate: ConfidenceGate | None = None
        self.quarantine_store: QuarantineStore | None = None
        self.metrics: MetricsCollector | None = None
        self.ssrf_guard: SSRFGuard | None = None
        self.pii_redactor: PIIRedactor | None = None

        # Playwright
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._gemini_api_key = gemini_api_key

    async def initialize(self) -> None:
        """Initialize all stores, load configs, start Playwright, wire layers."""
        setup_logging()

        # Storage
        await self.sqlite_store.initialize()
        await self.redis_client.connect()

        # Load configs
        self._load_domain_configs()
        self._load_business_rules()
        self._load_volatility_profiles()

        # Layer 1 — Compliance
        manifest_loader = LegalManifestLoader(
            manifests_dir=os.path.join(self.config_path, "manifests")
        )
        self.compliance_gate = ComplianceGate(
            manifest_loader=manifest_loader,
            config_path=os.path.join(self.config_path, "scraping_postures.yaml")
        )
        self.robots_checker = RobotsChecker()

        # Layer 2 — Rate Limiting
        self.rate_limiter = DistributedRateLimiter(redis_url=self.redis_client.url)

        # Layer 3 — Extraction
        self.locator_registry = LocatorRegistry()
        for config in self.domain_configs.values():
            self.locator_registry.load_from_config(config)

        self.lkg_store = LKGStore()
        await self.lkg_store.initialize(self.db_path)

        self.data_plane = DataPlane(
            registry=self.locator_registry,
            lkg_store=self.lkg_store,
        )

        # Layer 4 — Validation
        type_validator = TypeValidator()
        biz_validator = BusinessRuleValidator(self.business_rules_config or BusinessRulesConfig())
        stat_validator = StatisticalValidator(profiles=self.volatility_config or VolatilityProfilesConfig())
        await stat_validator.initialize(self.db_path)
        self.validation_pipeline = ValidationPipeline(
            type_validator=type_validator,
            business_validator=biz_validator,
            stat_validator=stat_validator,
        )

        # Layer 5 — Circuit Breakers
        self.spatial_breaker = SpatialBreaker()
        await self.spatial_breaker.initialize(self.db_path)
        self.temporal_breaker = TemporalBreaker()
        await self.temporal_breaker.initialize(self.db_path)

        # Layer 6 — Healing
        self.sanitizer = AXTreeSanitizer()
        self.scorer = ConfidenceScorer()
        self.healing_agent = HealingAgent(api_key=self._gemini_api_key)

        # Layer 7 — Cross-Validation
        self.cross_validator = CrossValidator()
        await self.cross_validator.initialize(self.db_path)

        # Layer 8 — Confidence & Quarantine
        self.confidence_gate = ConfidenceGate()
        self.quarantine_store = QuarantineStore()
        await self.quarantine_store.initialize(self.db_path, self.cold_storage.base_path)

        # Layer 9 — Telemetry
        self.metrics = MetricsCollector()

        # Security
        self.ssrf_guard = SSRFGuard()
        self.pii_redactor = PIIRedactor()

        # Playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

        logger.info("pipeline_initialized", domains=list(self.domain_configs.keys()))

    async def shutdown(self) -> None:
        """Close browser, stores, and connections gracefully."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await self.sqlite_store.close()
        await self.redis_client.close()
        logger.info("pipeline_shutdown")

    async def scrape(self, request: ScrapingRequest) -> ScrapingResponse:
        """Execute the full 9-layer scraping pipeline for a single page (§7).

        Returns ScrapingResponse with extracted data, quarantined fields,
        validation results, and drift events.
        """
        assert self._browser, "Pipeline not initialized. Call initialize() first."
        assert self.compliance_gate
        assert self.rate_limiter
        assert self.data_plane
        assert self.validation_pipeline
        assert self.spatial_breaker
        assert self.temporal_breaker
        assert self.healing_agent
        assert self.sanitizer
        assert self.scorer
        assert self.cross_validator
        assert self.confidence_gate
        assert self.quarantine_store
        assert self.metrics
        assert self.lkg_store
        assert self.locator_registry
        assert self.pii_redactor

        domain = request.domain
        url = request.url
        response = ScrapingResponse(
            request_id=request.request_id,
            url=url,
            domain=domain,
        )
        drift_events: list[DriftEvent] = []
        domain_config = self.domain_configs.get(domain)

        if not domain_config:
            response.success = False
            response.error = f"No configuration found for domain '{domain}'"
            logger.error("no_domain_config", domain=domain)
            return response

        try:
            # ── Step 1: Compliance + Rate Limiting ──
            await self.compliance_gate.check_compliance(domain, url)
            self.metrics.record_extraction(domain, success=True)

            allowed, wait = await self.rate_limiter.acquire_token(domain)
            if not allowed:
                raise RateLimitExceededError(domain, wait)

            # ── Step 2: Deterministic Extraction ──
            context = await self._browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                extraction_results = await self.data_plane.extract_page(
                    page, domain_config
                )
                response.extraction_results = extraction_results

                failed_fields: list[ExtractionResult] = []
                successful_fields: list[ExtractionResult] = []

                for result in extraction_results:
                    if result.success:
                        successful_fields.append(result)
                        response.fields[result.field_name] = result.value
                    else:
                        failed_fields.append(result)

                # ── Step 3: Update LKG for successful extractions ──
                for result in successful_fields:
                    try:
                        ax_neighborhood = await self.data_plane.capture_aria_snapshot(
                            page, result.selector_used
                        )
                        snapshot = LKGSnapshot(
                            domain=domain,
                            field_name=result.field_name,
                            selector=result.selector_used,
                            strategy=result.strategy,
                            ax_tree_neighborhood=ax_neighborhood,
                            text_signature=str(result.value)[:200],
                            sample_value=result.value,
                            page_url=url,
                        )
                        await self.lkg_store.push_snapshot(snapshot)
                    except Exception as e:
                        logger.warning(
                            "lkg_update_failed",
                            field=result.field_name,
                            error=str(e),
                        )

                # ── Step 4: Handle failed fields ──
                if failed_fields:
                    # Step 4a: Spatial breaker check
                    total = len(extraction_results)
                    failed_count = len(failed_fields)
                    drift_type = await self.spatial_breaker.check_and_classify(
                        domain, total_fields=total, failed_fields=failed_count
                    )

                    if drift_type == DriftType.GLOBAL:
                        self.metrics.set_breaker_state(
                            domain, "spatial", BreakerState.OPEN
                        )
                        raise GlobalDriftError(domain, failed_count / total)

                    # Process each failed field individually
                    for failed_result in failed_fields:
                        field_name = failed_result.field_name
                        field_def = next(
                            (f for f in domain_config.fields if f.name == field_name),
                            None,
                        )
                        if not field_def:
                            continue

                        heal_start = time.monotonic()
                        drift_event = DriftEvent(
                            domain=domain,
                            field_name=field_name,
                            drift_type=DriftType.LOCAL,
                            old_selector=failed_result.selector_used,
                        )

                        try:
                            # Step 4b: Temporal breaker check
                            temporal_state = await self.temporal_breaker.check_field(
                                domain, field_name
                            )
                            if temporal_state == BreakerState.REQUIRES_HUMAN_INTERVENTION:
                                raise ThrashLimitError(
                                    domain, field_name, 3, 48
                                )

                            # Step 4c: Sanitize + Heal
                            raw_ax_tree = await self.data_plane.capture_aria_snapshot(page)
                            lkg = await self.lkg_store.get_latest(domain, field_name)

                            repair_result, confidence, warnings = (
                                await self.healing_agent.heal_field(
                                    field=field_def,
                                    broken_selector=failed_result.selector_used,
                                    raw_ax_tree=raw_ax_tree,
                                    lkg_snapshot=lkg,
                                    sanitizer=self.sanitizer,
                                    scorer=self.scorer,
                                )
                            )

                            for w in warnings:
                                logger.warning(
                                    "injection_pattern_detected",
                                    domain=domain,
                                    field=field_name,
                                    pattern=w,
                                )

                            self.metrics.record_confidence_score(
                                domain, field_name, confidence
                            )

                            # Step 4d: Cross-validate
                            passed, pass_count, total_holdout = (
                                await self.cross_validator.validate_selector(
                                    domain=domain,
                                    field=field_def,
                                    proposed_selector=repair_result.primary_selector,
                                    strategy=repair_result.selector_strategy,
                                    holdout_urls=domain_config.holdout_urls,
                                    browser_context=context,
                                )
                            )

                            if not passed:
                                # Check for uniform failure → route to spatial breaker
                                is_uniform = (
                                    await self.cross_validator.check_uniform_failure(
                                        domain, pass_count, total_holdout
                                    )
                                )
                                if is_uniform:
                                    self.metrics.record_drift(
                                        domain, field_name, "global"
                                    )
                                drift_event.outcome = HealingOutcome.REJECTED_OVERFIT
                                raise CrossValidationError(
                                    domain, field_name, pass_count, total_holdout
                                )

                            # Step 4e: Confidence gate
                            approved = self.confidence_gate.evaluate(
                                confidence, field_name, domain
                            )

                            heal_duration = time.monotonic() - heal_start

                            if approved:
                                # Hot-reload selector
                                await self.locator_registry.update_locator(
                                    domain,
                                    field_name,
                                    repair_result.primary_selector,
                                    repair_result.selector_strategy,
                                )
                                await self.temporal_breaker.record_repair(
                                    domain,
                                    field_name,
                                    failed_result.selector_used,
                                    repair_result.primary_selector,
                                    confidence,
                                )
                                drift_event.new_selector = repair_result.primary_selector
                                drift_event.confidence_score = confidence
                                drift_event.outcome = HealingOutcome.AUTO_APPROVED
                                drift_event.auto_healed = True
                                drift_event.time_to_heal_seconds = heal_duration

                                self.metrics.record_healing_attempt(
                                    domain, field_name, "auto_approved", heal_duration
                                )

                                # Re-extract with healed selector
                                try:
                                    re_result = await self.data_plane.extract_field(
                                        page, field_def, domain
                                    )
                                    if re_result.success:
                                        response.fields[field_name] = re_result.value
                                except Exception:
                                    pass  # Extraction with new selector failed; field stays nulled

                            else:
                                # Quarantine
                                record = QuarantineRecord(
                                    domain=domain,
                                    field_name=field_name,
                                    page_url=url,
                                    broken_selector=failed_result.selector_used,
                                    proposed_selector=repair_result.primary_selector,
                                    confidence_score=confidence,
                                )
                                sanitized_tree, _ = self.sanitizer.sanitize(raw_ax_tree)
                                redacted_tree = self.pii_redactor.redact(sanitized_tree)
                                await self.quarantine_store.quarantine(record, redacted_tree)

                                response.quarantined_fields.append(field_name)
                                response.fields[field_name] = None

                                drift_event.outcome = HealingOutcome.QUARANTINED
                                drift_event.confidence_score = confidence
                                drift_event.time_to_heal_seconds = heal_duration

                                self.metrics.record_quarantine(domain, field_name)
                                self.metrics.record_healing_attempt(
                                    domain, field_name, "quarantined", heal_duration
                                )

                        except ThrashLimitError:
                            response.fields[field_name] = None
                            response.quarantined_fields.append(field_name)
                            drift_event.outcome = HealingOutcome.REJECTED_BREAKER
                            self.metrics.set_breaker_state(
                                domain, "temporal", BreakerState.REQUIRES_HUMAN_INTERVENTION
                            )
                            logger.warning(
                                "thrash_limit_hit",
                                domain=domain,
                                field=field_name,
                            )

                        except (HealingError, CrossValidationError) as e:
                            response.fields[field_name] = None
                            response.quarantined_fields.append(field_name)
                            heal_duration = time.monotonic() - heal_start
                            drift_event.outcome = HealingOutcome.FAILED
                            drift_event.time_to_heal_seconds = heal_duration
                            self.metrics.record_healing_attempt(
                                domain, field_name, "failed", heal_duration
                            )
                            logger.error(
                                "healing_failed",
                                domain=domain,
                                field=field_name,
                                error=str(e),
                            )

                        drift_event.resolved_at = datetime.now(timezone.utc)
                        drift_events.append(drift_event)
                        self.metrics.record_drift(domain, field_name, drift_event.drift_type.value)

            finally:
                await context.close()

            response.drift_events = drift_events
            response.success = True
            self.metrics.record_extraction(domain, success=True)

        except ComplianceError as e:
            response.success = False
            response.error = str(e)
            logger.error("compliance_blocked", domain=domain, error=str(e))

        except RateLimitExceededError as e:
            response.success = False
            response.error = str(e)
            logger.warning("rate_limited", domain=domain, wait=e.details.get("wait_seconds"))

        except GlobalDriftError as e:
            response.success = False
            response.error = str(e)
            logger.critical("global_drift", domain=domain, ratio=e.details.get("failed_ratio"))

        except CircuitBreakerOpenError as e:
            response.success = False
            response.error = str(e)
            logger.error("breaker_open", domain=domain)

        except Exception as e:
            response.success = False
            response.error = f"Unexpected error: {e}"
            logger.exception("pipeline_error", domain=domain, url=url)

        response.completed_at = datetime.now(timezone.utc)
        logger.info(
            "scrape_complete",
            domain=domain,
            url=url,
            success=response.success,
            fields_extracted=len(response.fields),
            quarantined=len(response.quarantined_fields),
            drift_events=len(response.drift_events),
        )

        return response

    # ──────────────────────────────────────────────
    # Config Loading
    # ──────────────────────────────────────────────

    def _load_domain_configs(self) -> None:
        """Load all domain configs from config/domains/*.yaml."""
        pattern = os.path.join(self.config_path, "domains", "*.yaml")
        for filepath in glob.glob(pattern):
            try:
                with open(filepath, "r") as f:
                    data = yaml.safe_load(f)
                if data and "domain" in data:
                    # Normalize rate_limit nested dict to flat fields
                    if "rate_limit" in data:
                        rl = data.pop("rate_limit")
                        data["rate_limit_rpm"] = rl.get("requests_per_minute", 30)
                        data["burst_capacity"] = rl.get("burst_capacity", 5)
                    config = DomainConfig(**data)
                    self.domain_configs[config.domain] = config
                    logger.info("domain_config_loaded", domain=config.domain)
            except Exception as e:
                logger.warning("domain_config_load_failed", file=filepath, error=str(e))

    def _load_business_rules(self) -> None:
        """Load business rules from config/business_rules.yaml."""
        path = os.path.join(self.config_path, "business_rules.yaml")
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            if data:
                self.business_rules_config = BusinessRulesConfig(**data)
                logger.info("business_rules_loaded", count=len(self.business_rules_config.rules))
        except FileNotFoundError:
            logger.warning("business_rules_not_found", path=path)
            self.business_rules_config = BusinessRulesConfig()
        except Exception as e:
            logger.warning("business_rules_load_failed", error=str(e))
            self.business_rules_config = BusinessRulesConfig()

    def _load_volatility_profiles(self) -> None:
        """Load volatility profiles from config/volatility_profiles.yaml."""
        path = os.path.join(self.config_path, "volatility_profiles.yaml")
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            if data:
                self.volatility_config = VolatilityProfilesConfig(**data)
                logger.info("volatility_profiles_loaded")
        except FileNotFoundError:
            logger.warning("volatility_profiles_not_found", path=path)
            self.volatility_config = VolatilityProfilesConfig()
        except Exception as e:
            logger.warning("volatility_profiles_load_failed", error=str(e))
            self.volatility_config = VolatilityProfilesConfig()
