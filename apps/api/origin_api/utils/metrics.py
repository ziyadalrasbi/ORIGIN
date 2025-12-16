"""Prometheus metrics."""

from prometheus_client import Counter, Histogram, Gauge

# Request metrics
ingest_requests = Counter(
    "origin_ingest_requests_total",
    "Total ingest requests",
    ["tenant_id", "decision"],
)

ingest_duration = Histogram(
    "origin_ingest_duration_seconds",
    "Ingest request duration",
    ["tenant_id"],
)

active_uploads = Gauge(
    "origin_active_uploads",
    "Active uploads being processed",
)

# Policy metrics
policy_evaluations = Counter(
    "origin_policy_evaluations_total",
    "Total policy evaluations",
    ["policy_version", "decision"],
)

# ML metrics
ml_inference_duration = Histogram(
    "origin_ml_inference_duration_seconds",
    "ML inference duration",
)

# Evidence pack metrics
evidence_packs_generated = Counter(
    "origin_evidence_packs_generated_total",
    "Total evidence packs generated",
    ["format"],
)

# Webhook metrics
webhook_deliveries = Counter(
    "origin_webhook_deliveries_total",
    "Total webhook deliveries",
    ["status"],
)

# IP allowlist metrics
ip_allowlist_parse_error = Counter(
    "origin_ip_allowlist_parse_error_total",
    "IP allowlist parse errors",
    ["fail_open"],
)

ip_allowlist_error = Counter(
    "origin_ip_allowlist_error_total",
    "IP allowlist errors",
    ["fail_open"],
)


def increment_counter(name: str, labels: dict = None):
    """Helper to increment a counter metric."""
    # This is a simple wrapper - in production, use proper Prometheus client
    # For now, we'll just log the metric increment
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"Metric increment: {name} with labels {labels}")

