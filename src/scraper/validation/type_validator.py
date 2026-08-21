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
        """
        field_name = field.name
        is_required = getattr(field, "required", False)

        if value is None or (isinstance(value, str) and not value.strip()):
            if is_required:
                return ValidationResult(
                    field_name=field_name,
                    passed=False,
                    check_type=ValidationCheckType.TYPE,
                    failure_reason=f"Field '{field_name}' is required but value is empty."
                )
            return ValidationResult(
                field_name=field_name,
                passed=True,
                check_type=ValidationCheckType.TYPE,
                failure_reason=None
            )

        field_type = getattr(field, "field_type", getattr(field, "type", "string")).lower()

        try:
            if field_type == "string":
                if not isinstance(value, str):
                    value = str(value)
                if is_required and not value.strip():
                    return ValidationResult(
                        field_name=field_name,
                        passed=False,
                        check_type=ValidationCheckType.TYPE,
                        failure_reason=f"Field '{field_name}' requires non-empty string."
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
                        field_name=field_name,
                        passed=False,
                        check_type=ValidationCheckType.TYPE,
                        failure_reason=f"Field '{field_name}' must be a valid HTTP/HTTPS URL."
                    )
            else:
                logger.warning("Unknown field type, treating as string", field_type=field_type)
                
        except (ValueError, TypeError) as e:
            return ValidationResult(
                field_name=field_name,
                passed=False,
                check_type=ValidationCheckType.TYPE,
                failure_reason=f"Type conversion failed for '{field_name}': {str(e)}"
            )

        return ValidationResult(
            field_name=field_name,
            passed=True,
            check_type=ValidationCheckType.TYPE,
            failure_reason=None
        )

    def _parse_float(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        
        val_str = str(value).strip()
        clean_str = re.sub(r'[^\d.]', '', val_str)
        if not clean_str:
            raise ValueError(f"Cannot parse '{value}' as float")
        return float(clean_str)
        
    def _parse_int(self, value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
            
        val_str = str(value).strip()
        clean_str = re.sub(r'[^\d-]', '', val_str)
        if not clean_str:
            raise ValueError(f"Cannot parse '{value}' as int")
        return int(clean_str)

    def _parse_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        
        val_str = str(value).strip().lower()
        if val_str in ("true", "yes", "1", "in stock"):
            return True
        if val_str in ("false", "no", "0", "out of stock"):
            return False
            
        raise ValueError(f"Cannot parse '{value}' as boolean")

    def _parse_date(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
            
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
