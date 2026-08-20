import re
from typing import Any

class PIIRedactor:
    """Regex-based PII detection and redaction."""

    # Note: These are simplified regexes for example purposes.
    PATTERNS = {
        'EMAIL': re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
        'PHONE': re.compile(r'(?:\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}'),
        'SSN': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
        'CREDIT_CARD': re.compile(r'\b(?:\d[ -]*?){13,16}\b'),
        'IPV4': re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    }

    def __init__(self, allow_fields: set[str] | None = None) -> None:
        self.allow_fields = allow_fields or set()

    def redact(self, text: str, field_name: str | None = None) -> str:
        """Replaces PII with [REDACTED_TYPE]."""
        if not isinstance(text, str):
            return text
            
        if field_name and field_name in self.allow_fields:
            return text
            
        redacted_text = text
        for pii_type, pattern in self.PATTERNS.items():
            # For credit card we might want Luhn check in a real scenario, but regex substitution is simple here
            redacted_text = pattern.sub(f'[REDACTED_{pii_type}]', redacted_text)
            
        return redacted_text

    def scan(self, text: str) -> list[dict[str, Any]]:
        """Returns list of matches without redacting."""
        if not isinstance(text, str):
            return []
            
        results = []
        for pii_type, pattern in self.PATTERNS.items():
            for match in pattern.finditer(text):
                results.append({
                    'type': pii_type,
                    'start': match.start(),
                    'end': match.end(),
                    'match': match.group()
                })
        return results

    def redact_dict(self, data: dict[str, Any], skip_fields: set[str] | None = None) -> dict[str, Any]:
        """Redact all string values in a dict."""
        skip = skip_fields or set()
        result = {}
        for k, v in data.items():
            if k in skip:
                result[k] = v
            elif isinstance(v, str):
                result[k] = self.redact(v, field_name=k)
            elif isinstance(v, dict):
                result[k] = self.redact_dict(v, skip_fields=skip)
            else:
                result[k] = v
        return result
