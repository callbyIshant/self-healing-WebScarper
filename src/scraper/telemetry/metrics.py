from prometheus_client import Counter, Histogram, Gauge, start_http_server
from scraper.core.enums import BreakerState

class MetricsCollector:
    """Wraps prometheus_client metrics for all pipeline events."""
    
    def __init__(self) -> None:
        self.scraper_extraction_total = Counter(
            'scraper_extraction_total', 
            'Total extraction attempts', 
            ['domain', 'status']
        )
        self.scraper_drift_events_total = Counter(
            'scraper_drift_events_total',
            'Drift detections',
            ['domain', 'field', 'drift_type']
        )
        self.scraper_healing_attempts_total = Counter(
            'scraper_healing_attempts_total',
            'Healing attempts with outcome',
            ['domain', 'field', 'outcome']
        )
        self.scraper_healing_duration_seconds = Histogram(
            'scraper_healing_duration_seconds',
            'Time spent in healing',
            ['domain']
        )
        self.scraper_confidence_scores = Histogram(
            'scraper_confidence_scores',
            'Distribution of confidence scores',
            ['domain', 'field']
        )
        self.scraper_circuit_breaker_state = Gauge(
            'scraper_circuit_breaker_state',
            'Current breaker state (0=closed, 1=open, 2=half_open, 3=requires_human)',
            ['domain', 'breaker_type']
        )
        self.scraper_quarantine_total = Counter(
            'scraper_quarantine_total',
            'Quarantined records',
            ['domain', 'field']
        )
        self.scraper_false_positive_repairs_total = Counter(
            'scraper_false_positive_repairs_total',
            'False positive repairs tracked over time',
            ['domain', 'field']
        )
        self.scraper_validation_failures_total = Counter(
            'scraper_validation_failures_total',
            'Validation failures',
            ['domain', 'field', 'check_type']
        )

    def record_extraction(self, domain: str, success: bool) -> None:
        status = 'success' if success else 'failure'
        self.scraper_extraction_total.labels(domain=domain, status=status).inc()

    def record_drift(self, domain: str, field: str, drift_type: str) -> None:
        self.scraper_drift_events_total.labels(domain=domain, field=field, drift_type=drift_type).inc()

    def record_healing_attempt(self, domain: str, field: str, outcome: str, duration_seconds: float) -> None:
        self.scraper_healing_attempts_total.labels(domain=domain, field=field, outcome=outcome).inc()
        self.scraper_healing_duration_seconds.labels(domain=domain).observe(duration_seconds)

    def record_confidence_score(self, domain: str, field: str, score: float) -> None:
        self.scraper_confidence_scores.labels(domain=domain, field=field).observe(score)

    def set_breaker_state(self, domain: str, breaker_type: str, state: BreakerState) -> None:
        state_mapping = {
            BreakerState.CLOSED: 0,
            BreakerState.OPEN: 1,
            BreakerState.HALF_OPEN: 2,
            BreakerState.REQUIRES_HUMAN_INTERVENTION: 3
        }
        val = state_mapping.get(state, 0)
        self.scraper_circuit_breaker_state.labels(domain=domain, breaker_type=breaker_type).set(val)

    def record_quarantine(self, domain: str, field: str) -> None:
        self.scraper_quarantine_total.labels(domain=domain, field=field).inc()

    def record_false_positive(self, domain: str, field: str) -> None:
        self.scraper_false_positive_repairs_total.labels(domain=domain, field=field).inc()

    def record_validation_failure(self, domain: str, field: str, check_type: str) -> None:
        self.scraper_validation_failures_total.labels(domain=domain, field=field, check_type=check_type).inc()

    def start_metrics_server(self, port: int = 9090) -> None:
        """Starts Prometheus HTTP server."""
        start_http_server(port)
