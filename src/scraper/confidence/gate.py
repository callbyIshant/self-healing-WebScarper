"""
Layer 8: Confidence Gate

Compares confidence score against empirically derived threshold.
"""

import structlog

logger = structlog.get_logger(__name__)

class ConfidenceGate:
    """
    Compares confidence score against empirically derived threshold.
    """

    def __init__(self, threshold: float = 0.75) -> None:
        """Initialize ConfidenceGate with a threshold."""
        self._threshold = threshold

    def evaluate(self, confidence_score: float, field_name: str, domain: str) -> bool:
        """
        Evaluate if the confidence score meets the threshold.
        Returns True if score >= threshold (approve), False otherwise (quarantine).
        """
        approved = confidence_score >= self._threshold
        logger.info(
            "confidence_evaluation",
            domain=domain,
            field_name=field_name,
            confidence_score=confidence_score,
            threshold=self._threshold,
            approved=approved
        )
        return approved

    def update_threshold(self, new_threshold: float) -> None:
        """Update threshold after calibration."""
        logger.info("updating_confidence_threshold", old=self._threshold, new=new_threshold)
        self._threshold = new_threshold

    @property
    def threshold(self) -> float:
        """Get current threshold."""
        return self._threshold
