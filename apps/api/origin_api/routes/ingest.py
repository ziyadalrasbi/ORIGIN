"""Ingest endpoint for content submissions."""

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.identity.resolver import IdentityResolver
from origin_api.ledger.certificate import CertificateService
from origin_api.ledger.service import LedgerService
from origin_api.ml.inference import get_inference_service
from origin_api.models import Account, RiskSignal, Upload
from origin_api.models.tenant import Tenant
from origin_api.policy.engine import PolicyEngine
from origin_api.provenance.pvid import PVIDGenerator
from origin_api.webhooks.service import WebhookService

router = APIRouter(prefix="/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    """Ingest request model."""

    account_external_id: str = Field(..., description="External account identifier")
    account_type: str = Field(default="user", description="Account type: user, organization, bot, etc.")
    display_name: Optional[str] = Field(None, description="Account display name")
    upload_external_id: str = Field(..., description="External upload identifier")
    metadata: Optional[dict] = Field(default_factory=dict, description="Upload metadata (title, collaborators, etc.)")
    content_ref: Optional[str] = Field(None, description="URL or reference to content")
    fingerprints: Optional[dict] = Field(None, description="Content fingerprints (audio_hash, perceptual_hash, etc.)")
    device_context: Optional[dict] = Field(None, description="Device context (device_hash, ip, user_agent, etc.)")


class IngestResponse(BaseModel):
    """Ingest response model."""

    ingestion_id: str
    decision: str  # ALLOW, REVIEW, QUARANTINE, REJECT
    policy_version: str
    risk_score: Optional[float] = None
    assurance_score: Optional[float] = None
    certificate_id: Optional[str] = None
    ledger_hash: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    evidence_pack_status: str = "pending"
    evidence_pack_request_url: Optional[str] = None


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_200_OK)
async def ingest(
    request_data: IngestRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Ingest a content submission and return a decision."""
    # Get tenant from request state (set by auth middleware)
    tenant: Tenant = request.state.tenant

    # Generate ingestion ID
    ingestion_id = str(uuid.uuid4())

    # Get correlation ID from request state
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    # Get or create account
    account = (
        db.query(Account)
        .filter(
            Account.tenant_id == tenant.id,
            Account.external_id == request_data.account_external_id,
        )
        .first()
    )

    if not account:
        account = Account(
            tenant_id=tenant.id,
            external_id=request_data.account_external_id,
            type=request_data.account_type,
            display_name=request_data.display_name,
            risk_state="unknown",
        )
        db.add(account)
        db.flush()

    # Step 5: Identity Resolution
    identity_resolver = IdentityResolver(db)
    device_hash = request_data.device_context.get("device_hash") if request_data.device_context else None
    ip_hash = None
    if request_data.device_context and "ip" in request_data.device_context:
        ip_hash = hashlib.sha256(request_data.device_context["ip"].encode()).hexdigest()

    identity_result = identity_resolver.resolve_identity(
        tenant.id,
        account.id,
        request_data.account_external_id,
        device_hash,
        ip_hash,
    )

    # Step 6: Provenance/PVID
    pvid_generator = PVIDGenerator(db)
    pvid_result = pvid_generator.resolve_pvid(
        tenant.id,
        request_data.content_ref,
        request_data.fingerprints,
        request_data.metadata,
    )

    # Step 7-8: ML Risk Signals
    ml_service = get_inference_service()
    
    # Compute account age in days
    from datetime import timezone
    now = datetime.now(timezone.utc)
    # Ensure account.created_at is timezone-aware for comparison
    account_created = account.created_at
    if account_created.tzinfo is None:
        account_created = account_created.replace(tzinfo=timezone.utc)
    account_age_days = max(0, (now - account_created).days)
    
    # Get upload velocity (uploads in last 24 hours)
    from datetime import timedelta
    window_start = now - timedelta(hours=24)
    # Query uploads in the last 24 hours
    # Note: received_at is stored as timezone-naive UTC datetime
    window_start_naive = window_start.replace(tzinfo=None)
    upload_velocity = (
        db.query(Upload)
        .filter(
            Upload.tenant_id == tenant.id,
            Upload.account_id == account.id,
            Upload.received_at >= window_start_naive,
        )
        .count()
    )

    risk_signals = ml_service.compute_risk_signals(
        account_age_days=account_age_days,
        shared_device_count=identity_result["features"]["shared_device_count"],
        prior_quarantine_count=identity_result["features"]["prior_quarantine_count"],
        identity_confidence=identity_result["identity_confidence"],
        upload_velocity=upload_velocity,
        prior_sightings_count=pvid_result["sightings"]["prior_sightings_count"],
    )

    # Step 9: Policy Evaluation
    policy_engine = PolicyEngine(db)
    decision_result = policy_engine.evaluate_decision(
        tenant_id=tenant.id,
        risk_score=risk_signals["risk_score"],
        assurance_score=risk_signals["assurance_score"],
        anomaly_score=risk_signals["anomaly_score"],
        synthetic_likelihood=risk_signals["synthetic_likelihood"],
        has_prior_quarantine=pvid_result["sightings"]["has_prior_quarantine"],
        has_prior_reject=pvid_result["sightings"]["has_prior_reject"],
        prior_sightings_count=pvid_result["sightings"]["prior_sightings_count"],
        identity_confidence=identity_result["identity_confidence"],
    )

    # Create upload record
    upload = Upload(
        tenant_id=tenant.id,
        ingestion_id=ingestion_id,
        external_id=request_data.upload_external_id,
        account_id=account.id,
        title=request_data.metadata.get("title") if request_data.metadata else None,
        metadata_json=request_data.metadata,
        content_ref=request_data.content_ref,
        fingerprints_json=request_data.fingerprints,
        received_at=datetime.utcnow(),
        pvid=pvid_result["pvid"],
        decision=decision_result["decision"],
        policy_version=decision_result["policy_version"],
        risk_score=risk_signals["risk_score"],
        assurance_score=risk_signals["assurance_score"],
    )
    db.add(upload)
    db.flush()

    # Store risk signals
    for signal_type, value in risk_signals.items():
        signal = RiskSignal(
            tenant_id=tenant.id,
            upload_id=upload.id,
            signal_type=signal_type,
            value=value,
            details_json={"source": "ml_inference"},
        )
        db.add(signal)

    # Step 10: Ledger & Certificate
    ledger_service = LedgerService(db)
    certificate_service = CertificateService(db)

    # Prepare inputs and outputs for certificate
    inputs = {
        "account_external_id": request_data.account_external_id,
        "upload_external_id": request_data.upload_external_id,
        "metadata": request_data.metadata,
        "fingerprints": request_data.fingerprints,
    }

    outputs = {
        "decision": decision_result["decision"],
        "risk_score": risk_signals["risk_score"],
        "assurance_score": risk_signals["assurance_score"],
        "triggered_rules": decision_result["triggered_rules"],
        "reason_codes": decision_result["reason_codes"],
    }

    # Append ledger event
    ledger_event = ledger_service.append_event(
        tenant_id=tenant.id,
        correlation_id=correlation_id,
        event_type="ingest.decision",
        payload={
            "ingestion_id": ingestion_id,
            "upload_id": upload.id,
            "decision": decision_result["decision"],
            "inputs": inputs,
            "outputs": outputs,
        },
    )

    # Generate certificate
    certificate = certificate_service.generate_certificate(
        tenant_id=tenant.id,
        upload_id=upload.id,
        policy_version=decision_result["policy_version"],
        inputs=inputs,
        outputs=outputs,
        ledger_hash=ledger_event.event_hash,
    )

    db.commit()

    # Step 12: Webhook delivery (async)
    try:
        webhook_service = WebhookService(db)
        webhook_service.deliver_webhook(
            tenant.id,
            "decision.created",
            {
                "ingestion_id": ingestion_id,
                "certificate_id": certificate.certificate_id,
                "decision": decision_result["decision"],
                "upload_id": upload.id,
            },
        )
    except Exception as e:
        # Log but don't fail the request
        print(f"Webhook delivery failed: {e}")

    return IngestResponse(
        ingestion_id=ingestion_id,
        decision=decision_result["decision"],
        policy_version=decision_result["policy_version"],
        risk_score=risk_signals["risk_score"],
        assurance_score=risk_signals["assurance_score"],
        certificate_id=certificate.certificate_id,
        ledger_hash=ledger_event.event_hash,
        reasons=decision_result["reason_codes"],
        evidence_pack_status="pending",
        evidence_pack_request_url=f"/v1/evidence-packs?certificate_id={certificate.certificate_id}",
    )

