import structlog
from typing import Any
import re

from scraper.core.models import BusinessRule, BusinessRulesConfig, ValidationResult
from scraper.core.enums import ValidationCheckType

logger = structlog.get_logger(__name__)

class BusinessRuleValidator:
    """
    Validates field values against configured business rules using a rule engine.
    Rules can be scoped by context and use various comparison operators.
    """

    def __init__(self, config: BusinessRulesConfig):
        """
        Initialize the validator with business rules configuration.
        
        Args:
            config: The parsed business rules configuration.
        """
        self.config = config

    def validate(self, field_name: str, value: Any, context: dict[str, Any] | None = None) -> list[ValidationResult]:
        """
        Evaluates all applicable business rules for a field.
        
        Args:
            field_name: The name of the field to validate.
            value: The extracted value.
            context: Optional context dictionary to determine rule applicability.
            
        Returns:
            A list of ValidationResult objects, one for each applicable rule evaluated.
        """
        results = []
        rules = getattr(self.config, "rules", [])
        
        applicable_rules = [
            rule for rule in rules 
            if getattr(rule, "field_name", None) == field_name and self._context_matches(getattr(rule, "context", None), context)
        ]

        if not applicable_rules:
            # If no rules apply, return an empty list (implicitly passes)
            return []

        for rule in applicable_rules:
            try:
                passed = self._evaluate_rule(rule, value)
                results.append(ValidationResult(
                    is_valid=passed,
                    check_type=ValidationCheckType.BUSINESS_RULE,
                    message=f"Rule {getattr(rule, 'id', 'unknown')} passed" if passed else f"Rule {getattr(rule, 'id', 'unknown')} failed for value {value}"
                ))
            except Exception as e:
                logger.error("Error evaluating business rule", rule_id=getattr(rule, "id", "unknown"), error=str(e))
                results.append(ValidationResult(
                    is_valid=False,
                    check_type=ValidationCheckType.BUSINESS_RULE,
                    message=f"Error evaluating rule {getattr(rule, 'id', 'unknown')}: {str(e)}"
                ))

        return results

    def _context_matches(self, rule_context: dict[str, Any] | None, actual_context: dict[str, Any] | None) -> bool:
        """Checks if the actual context satisfies the rule's required context."""
        if not rule_context:
            return True
            
        if actual_context is None:
            return False
            
        for k, v in rule_context.items():
            if actual_context.get(k) != v:
                return False
                
        return True

    def _evaluate_rule(self, rule: BusinessRule, value: Any) -> bool:
        """Evaluates a single rule operator against the value."""
        operator = getattr(rule, "operator", "").lower()
        target = getattr(rule, "target_value", None)
        
        if value is None:
            return False

        if operator == "gt":
            return float(value) > float(target)
        elif operator == "gte":
            return float(value) >= float(target)
        elif operator == "lt":
            return float(value) < float(target)
        elif operator == "lte":
            return float(value) <= float(target)
        elif operator == "eq":
            return str(value) == str(target)
        elif operator == "ne":
            return str(value) != str(target)
        elif operator == "min_length":
            return len(str(value)) >= int(target)
        elif operator == "max_length":
            return len(str(value)) <= int(target)
        elif operator == "regex":
            return bool(re.match(str(target), str(value)))
        elif operator == "in":
            if isinstance(target, list):
                return value in target
            return str(value) in str(target)
        else:
            raise ValueError(f"Unknown operator: {operator}")
