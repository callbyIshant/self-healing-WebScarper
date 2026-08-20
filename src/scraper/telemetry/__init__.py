"""
Telemetry layer for the self-healing web scraper.
Handles logging and metrics collection.
"""

from scraper.telemetry.logger import setup_logging, get_logger
from scraper.telemetry.metrics import MetricsCollector

__all__ = ["setup_logging", "get_logger", "MetricsCollector"]
