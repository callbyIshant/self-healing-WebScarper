import structlog
from typing import Any
import re
from datetime import datetime

from scraper.core.models import FieldDefinition, ValidationResult
from scraper.core.enums import ValidationCheckType

logger = structlog.get_logger(__name__)

class TypeValidator:
    """
    Generic type and format validation for extracted fields.
    Validates fields against their declared type without requiring per-site configuration.
    """

    def validate(self, field: FieldDefinition, value: Any) -> ValidationResult:
        """
        Validates a value against the field's declared type.
        
        Args:
            field: The FieldDefinition containing type information and requirements.
            value: The extracted value to validate.
            
        Returns:
            ValidationResult indicating success or failure of the type check.
        """
        if value is None or value == "":
            if getattr(field, "required", False):
                return ValidationResult(
                    is_valid=False,
                    check_type=ValidationCheckType.TYPE,
                    message=f"Field {field.name} is required but value is empty."
                )
            return ValidationResult(
                is_valid=True,
                check_type=ValidationCheckType.TYPE,
                message="Empty value for optional field."
            )

        field_type = getattr(field, "type", "string").lower()

        try:
            if field_type == "string":
                if not isinstance(value, str):
                    value = str(value)
                if getattr(field, "required", False) and not value.strip():
                    return ValidationResult(
                        is_valid=False,
                        check_type=ValidationCheckType.TYPE,
                        message=f"Field {field.name} requires non-empty string."
                    )
            
            elif field_type == "float":
                self._parse_float(value)
                
            elif field_type == "int":
                self._parse_int(value)
                
            elif field_type == "bool":
                self._parse_bool(value)
                
            elif field_type == "date":
                self._parse_date(value)
                
            elif field_type == "url":
                if not isinstance(value, str) or not re.match(r"^https?://", str(value)):
                    return ValidationResult(
                        is_valid=False,
                        check_type=ValidationCheckType.TYPE,
                        message=f"Field {field.name} must be a valid HTTP/HTTPS URL."
                    )
            else:
                logger.warning("Unknown field type, treating as string", field_type=field_type)
                
        except ValueError as e:
            return ValidationResult(
                is_valid=False,
                check_type=ValidationCheckType.TYPE,
                message=f"Type conversion failed for {field.name}: {str(e)}"
            )

        return ValidationResult(
            is_valid=True,
            check_type=ValidationCheckType.TYPE,
            message="Type validation passed."
        )

    def _parse_float(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        
        val_str = str(value).replace(",", "").strip()
        if val_str.startswith("$") or val_str.startswith("€") or val_str.startswith("£"):
            val_str = val_str[1:]
            
        return float(val_str)
        
    def _parse_int(self, value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
            
        val_str = str(value).replace(",", "").strip()
        return int(val_str)

    def _parse_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        
        val_str = str(value).strip().lower()
        if val_str in ("true", "yes", "1"):
            return True
        if val_str in ("false", "no", "0"):
            return False
            
        raise ValueError(f"Cannot parse {value} as boolean")

    def _parse_date(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
            
        # Try basic ISO 8601 parsing
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
