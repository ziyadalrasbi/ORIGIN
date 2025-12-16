"""Add performance indexes to database."""

# This would be an Alembic migration, but for reference:
# Indexes to add for performance:

INDEXES = [
    # Uploads table
    "CREATE INDEX IF NOT EXISTS idx_uploads_tenant_received ON uploads(tenant_id, received_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_uploads_decision ON uploads(decision);",
    "CREATE INDEX IF NOT EXISTS idx_uploads_pvid ON uploads(pvid) WHERE pvid IS NOT NULL;",
    
    # Identity relationships
    "CREATE INDEX IF NOT EXISTS idx_identity_relationships_from ON identity_relationships(from_entity_id, relationship_type);",
    "CREATE INDEX IF NOT EXISTS idx_identity_relationships_to ON identity_relationships(to_entity_id, relationship_type);",
    
    # Risk signals
    "CREATE INDEX IF NOT EXISTS idx_risk_signals_upload ON risk_signals(upload_id, signal_type);",
    
    # Ledger events
    "CREATE INDEX IF NOT EXISTS idx_ledger_events_tenant_created ON ledger_events(tenant_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_ledger_events_correlation ON ledger_events(correlation_id);",
    
    # Decision certificates
    "CREATE INDEX IF NOT EXISTS idx_certificates_upload ON decision_certificates(upload_id);",
    "CREATE INDEX IF NOT EXISTS idx_certificates_ledger_hash ON decision_certificates(ledger_hash);",
    
    # Evidence packs
    "CREATE INDEX IF NOT EXISTS idx_evidence_packs_certificate ON evidence_packs(certificate_id, status);",
    
    # Webhook deliveries
    "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status, next_retry_at) WHERE status = 'retrying';",
]

