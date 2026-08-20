import structlog
from typing import Any

from scraper.core.models import FieldDefinition, ValidationResult
from scraper.core.enums import VolatilityProfile
from scraper.validation.type_validator import TypeValidator
from scraper.validation.business_rules import BusinessRuleValidator
from scraper.validation.statistical import StatisticalValidator

logger = structlog.get_logger(__name__)

class ValidationPipeline:
    """
    Orchestrates the validation sequence: Type -> Business Rules -> Statistical.
    Short-circuits on early failures and aggregates all results.
    """

    def __init__(self, type_validator: TypeValidator, business_validator: BusinessRuleValidator, stat_validator: StatisticalValidator):
        self.type_validator = type_validator
        self.business_validator = business_validator
        self.stat_validator = stat_validator

    async def validate_extraction(self, domain: str, field: FieldDefinition, value: Any, item_key: str, context: dict[str, Any] | None = None, dom_context: str | None = None) -> list[ValidationResult]:
        """
        Runs the full validation pipeline on an extracted value.
        
        Args:
            domain: The site domain.
            field: The definition of the field being validated.
            value: The extracted value.
            item_key: The identifier for the item being scraped.
            context: Context dictionary for business rules.
            dom_context: Context string for statistical validation (e.g. DOM labels).
            
        Returns:
            A list of ValidationResult from all executed validators.
        """
        results: list[ValidationResult] = []
        
        # 1. Type Validation
        type_result = self.type_validator.validate(field, value)
        results.append(type_result)
        
        if not type_result.is_valid:
            logger.debug("Type validation failed, short-circuiting pipeline", field=field.name, value=value)
            return results
            
        # 2. Business Rules Validation
        biz_results = self.business_validator.validate(field.name, value, context)
        results.extend(biz_results)
        
        if any(not r.is_valid for r in biz_results):
            logger.debug("Business rules validation failed, short-circuiting pipeline", field=field.name)
            return results
            
        # 3. Statistical Validation (only applicable for numeric data typically)
        # Check if the field specifies a volatility profile and if it's numeric
        field_type = getattr(field, "type", "string").lower()
        if field_type in ("float", "int"):
            volatility = getattr(field, "volatility", VolatilityProfile.MODERATE)
            
            try:
                # Assuming value has been parseable since Type Validation passed
                num_value = float(str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip())
                stat_result = await self.stat_validator.validate(
                    domain=domain,
                    field_name=field.name,
                    item_key=item_key,
                    value=num_value,
                    volatility=volatility,
                    dom_context=dom_context
                )
                results.append(stat_result)
                
                # Update stats only if everything passed
                if stat_result.is_valid:
                    await self.stat_validator.update_stats(
                        domain=domain,
                        field_name=field.name,
                        item_key=item_key,
                        value=num_value
                    )
            except (ValueError, TypeError) as e:
                logger.warning("Could not convert value to float for statistical validation", error=str(e), value=value)
                
        return results
