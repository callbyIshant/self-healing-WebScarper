import logging
import re
from typing import Any
import structlog
from structlog.types import EventDict

TOKEN_REGEX = re.compile(r'(?P<key>(?:token|key|Authorization|api_key|password|secret)[^=]*)=(?P<val>[^&\s]+)', re.IGNORECASE)

def sanitize_log_value(value: str, max_length: int = 1000) -> str:
    """Truncates raw HTML and redact URLs containing tokens/credentials."""
    if not isinstance(value, str):
        value = str(value)
    
    if len(value) > max_length:
        value = value[:max_length] + f"... [TRUNCATED, original length: {len(value)}]"
    
    value = TOKEN_REGEX.sub(r'\g<key>=[REDACTED]', value)
    return value

def _sanitize_processor(logger: structlog.BoundLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Processor to sanitize log values in event dict."""
    for k, v in event_dict.items():
        if isinstance(v, str):
            event_dict[k] = sanitize_log_value(v)
    return event_dict

def setup_logging(log_level: str = 'INFO', json_output: bool = True) -> None:
    """Configure structlog with JSON output and context variables."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level, handlers=[logging.StreamHandler()])
    
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='iso'),
        _sanitize_processor,
    ]
    
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
        
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a structlog logger."""
    return structlog.get_logger(name)
