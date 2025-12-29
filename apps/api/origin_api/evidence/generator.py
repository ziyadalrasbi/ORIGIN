"""Evidence pack generation service."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from jinja2 import Template
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from origin_api.evidence.schema import (
    EvidencePackV2,
    TenantContext,
    CertificateContext,
    UploadContext,
    DecisionSummary,
    MLSignalsContext,
    RegulatoryProfile,
    RiskImpactAnalysis,
    IdentityHistoryContext,
    GovernanceContext,
    TechnicalTraceContext,
    AuditMetadata,
)
from origin_api.models import (
    DecisionCertificate,
    EvidencePack,
    Upload,
    LedgerEvent,
    Account,
    PolicyProfile,
    RiskSignal,
    Tenant,
)
from origin_api.settings import get_settings

settings = get_settings()


class EvidencePackGenerator:
    """Generate evidence packs in multiple formats."""

    def __init__(self, db: Session):
        """Initialize evidence pack generator."""
        self.db = db
        # Use absolute path that works both in container and host (via volume mount)
        self.storage_base = Path("/app/evidence_packs")  # Mounted to ./evidence_packs on host

    def _get_decision_color(self, decision: str) -> tuple:
        """Get color tuple for decision badge."""
        color_map = {
            "ALLOW": (46, 125, 50),  # Green
            "REVIEW": (237, 108, 2),  # Orange
            "QUARANTINE": (198, 40, 40),  # Red
            "REJECT": (156, 39, 176),  # Purple
        }
        return color_map.get(decision, (128, 128, 128))

    def _get_decision_explanation(self, decision: str, rationale: Optional[str] = None) -> str:
        """Get human-readable explanation for decision."""
        explanations = {
            "ALLOW": (
                "This content has been approved for distribution. The upload meets all risk thresholds "
                "and shows no signs of fraud, synthetic content, or anomalous behavior. The creator's "
                "identity is established and trustworthy."
            ),
            "REVIEW": (
                "This content requires manual review before distribution. The upload shows moderate risk "
                "signals that warrant human evaluation. Common reasons include: moderate risk scores, "
                "new creator accounts, or unusual patterns that need verification."
            ),
            "QUARANTINE": (
                "This content has been quarantined and is not approved for distribution. The upload shows "
                "high risk signals such as: high risk scores, synthetic/AI-generated content detection, "
                "anomalous behavior patterns, or prior quarantine history. Manual review is required."
            ),
            "REJECT": (
                "This content has been rejected and cannot be distributed. The upload shows extreme risk "
                "signals including: very high risk scores, prior reject history, or clear indicators of "
                "fraud or policy violations. This decision is final."
            ),
        }
        base = explanations.get(decision, "Decision made based on risk assessment.")
        if rationale:
            return f"{base}\n\nDetailed Rationale: {rationale}"
        return base

    def _get_score_color(self, score: float, threshold_low: float = 40, threshold_high: float = 70) -> tuple:
        """Get color for score visualization."""
        if score < threshold_low:
            return (46, 125, 50)  # Green
        elif score < threshold_high:
            return (237, 108, 2)  # Orange
        else:
            return (198, 40, 40)  # Red

    def _gather_evidence_data(
        self, certificate: DecisionCertificate, upload: Upload
    ) -> dict:
        """Gather all evidence data from database."""
        # Get ledger event
        ledger_event = (
            self.db.query(LedgerEvent)
            .filter(LedgerEvent.event_hash == certificate.ledger_hash)
            .first()
        )

        # Get account information
        account = None
        if upload.account_id:
            account = self.db.query(Account).filter(Account.id == upload.account_id).first()

        # Get policy profile
        policy_profile = (
            self.db.query(PolicyProfile)
            .filter(
                PolicyProfile.tenant_id == certificate.tenant_id,
                PolicyProfile.is_active == True,  # noqa: E712
            )
            .first()
        )

        # Get risk signals
        risk_signals = (
            self.db.query(RiskSignal)
            .filter(RiskSignal.upload_id == upload.id)
            .all()
        )

        # Extract decision trace from ledger
        decision_trace = {
            "decision": upload.decision,
            "risk_score": float(upload.risk_score) if upload.risk_score is not None else None,
            "assurance_score": float(upload.assurance_score) if upload.assurance_score is not None else None,
            "triggered_rules": [],
            "reason_codes": [],
            "rationale": None,
            "ml_signals": {},
        }

        if ledger_event and ledger_event.payload_json:
            decision_payload = ledger_event.payload_json.get("outputs", {})
            decision_trace = {
                "decision": decision_payload.get("decision", upload.decision),
                "risk_score": decision_payload.get("risk_score"),
                "assurance_score": decision_payload.get("assurance_score"),
                "triggered_rules": decision_payload.get("triggered_rules", []),
                "reason_codes": decision_payload.get("reason_codes", []),
                "rationale": decision_payload.get("rationale"),
                "ml_signals": decision_payload.get("ml_signals", {}),
            }

        # Build risk signals dict
        risk_signals_dict = {}
        for signal in risk_signals:
            risk_signals_dict[signal.signal_type] = {
                "value": float(signal.value),
                "details": signal.details_json or {},
            }

        # Merge with ML signals from decision trace
        if decision_trace.get("ml_signals"):
            for key, value in decision_trace["ml_signals"].items():
                if key not in risk_signals_dict:
                    risk_signals_dict[key] = {"value": value, "details": {}}

        return {
            "certificate": certificate,
            "upload": upload,
            "account": account,
            "policy_profile": policy_profile,
            "decision_trace": decision_trace,
            "risk_signals": risk_signals_dict,
            "ledger_event": ledger_event,
        }

    def generate_json(
        self, certificate: DecisionCertificate, upload: Upload, audience: str = "INTERNAL"
    ) -> dict:
        """Generate comprehensive JSON evidence pack (Evidence Pack v2).

        Returns a dict that conforms to EvidencePackV2 schema while maintaining
        backward compatibility with existing top-level keys.
        """
        data = self._gather_evidence_data(certificate, upload)
        decision_trace = data["decision_trace"]
        ml_signals = decision_trace.get("ml_signals", {})

        # Get tenant
        tenant = self.db.query(Tenant).filter(Tenant.id == upload.tenant_id).first()

        # Build EvidencePackV2
        evidence_v2 = self._build_evidence_pack_v2(
            certificate, upload, data, tenant, ml_signals, audience
        )

        # Convert to dict for backward compatibility
        evidence_dict = evidence_v2.model_dump(mode="json")

        # Preserve existing top-level keys for backward compatibility
        evidence_dict["certificate_id"] = certificate.certificate_id
        evidence_dict["issued_at"] = certificate.issued_at.isoformat()
        evidence_dict["decision"] = upload.decision
        evidence_dict["decision_explanation"] = self._get_decision_explanation(
            upload.decision, decision_trace.get("rationale")
        )
        evidence_dict["policy_version"] = certificate.policy_version
        evidence_dict["scores"] = {
            "risk_score": float(upload.risk_score) if upload.risk_score else None,
            "assurance_score": float(upload.assurance_score) if upload.assurance_score else None,
        }
        evidence_dict["risk_signals"] = data["risk_signals"]
        evidence_dict["decision_trace"] = decision_trace
        evidence_dict["integrity"] = {
            "inputs_hash": certificate.inputs_hash,
            "outputs_hash": certificate.outputs_hash,
            "ledger_hash": certificate.ledger_hash,
            "signature": certificate.signature,
        }

        return evidence_dict

    def _build_evidence_pack_v2(
        self,
        certificate: DecisionCertificate,
        upload: Upload,
        data: dict,
        tenant: Optional[Tenant],
        ml_signals: dict,
        audience: str,
    ) -> EvidencePackV2:
        """Build EvidencePackV2 instance from gathered data."""
        decision_trace = data["decision_trace"]
        policy_profile = data["policy_profile"]
        account = data["account"]
        ledger_event = data["ledger_event"]

        # Tenant Context
        tenant_context = TenantContext(
            tenant_id=upload.tenant_id,
            tenant_name=tenant.label if tenant else None,
            jurisdiction=["UNKNOWN"],  # Placeholder - can be populated from tenant metadata later
        )

        # Certificate Context
        certificate_context = CertificateContext(
            certificate_id=certificate.certificate_id,
            issued_at=certificate.issued_at,
            policy_version=certificate.policy_version,
            inputs_hash=certificate.inputs_hash,
            outputs_hash=certificate.outputs_hash,
            ledger_hash=certificate.ledger_hash,
            signature=certificate.signature,
            signature_algorithm="RSA-PSS-SHA256",
            key_fingerprint=None,  # Can be populated from certificate metadata
        )

        # Upload Context
        upload_context = UploadContext(
            ingestion_id=upload.ingestion_id,
            external_id=upload.external_id,
            received_at=upload.received_at,
            pvid=upload.pvid,
            metadata_json=upload.metadata_json,
            content_ref=upload.content_ref,
            account_id=upload.account_id,
            account_type=account.type if account else None,
            account_created_at=account.created_at if account and account.created_at else None,
        )

        # Decision Summary
        decision_mode = (
            policy_profile.decision_mode if policy_profile and policy_profile.decision_mode else "AUTO"
        )
        human_review_required = upload.decision in ["REVIEW", "QUARANTINE", "REJECT"]
        sla_guidance = (
            "60-minute review target for REVIEW decisions"
            if upload.decision == "REVIEW"
            else None
        )

        decision_summary = DecisionSummary(
            decision=upload.decision,
            decision_mode=decision_mode,
            decision_rationale=decision_trace.get("rationale"),
            reasons=decision_trace.get("reason_codes", []),  # Legacy field
            reason_codes=decision_trace.get("reason_codes", []),
            triggered_rules=decision_trace.get("triggered_rules", []),
            human_review_required=human_review_required,
            sla_guidance=sla_guidance,
        )

        # ML Signals Context
        risk_score = float(upload.risk_score) if upload.risk_score else 0.0
        assurance_score = float(upload.assurance_score) if upload.assurance_score else 0.0

        # Build feature contributions (simplified)
        feature_contributions = []
        if upload.account_id and account and account.created_at:
            account_age_days = (upload.received_at - account.created_at).days
            if account_age_days < 7:
                feature_contributions.append({
                    "feature": "account_age_days",
                    "direction": "negative",
                    "explanation": f"New account ({account_age_days} days old) increases risk",
                })
            elif account_age_days > 365:
                feature_contributions.append({
                    "feature": "account_age_days",
                    "direction": "positive",
                    "explanation": f"Established account ({account_age_days} days old) reduces risk",
                })

        if ml_signals.get("prior_quarantine_count", 0) > 0:
            feature_contributions.append({
                "feature": "prior_quarantine_count",
                "direction": "negative",
                "explanation": f"Prior quarantine history ({ml_signals.get('prior_quarantine_count')} instances) increases risk",
            })

        ml_signals_context = MLSignalsContext(
            risk_score=risk_score,
            assurance_score=assurance_score,
            anomaly_score=ml_signals.get("anomaly_score"),
            synthetic_likelihood=ml_signals.get("synthetic_likelihood"),
            identity_confidence=ml_signals.get("identity_confidence"),
            prior_sightings_count=ml_signals.get("prior_sightings_count"),
            prior_quarantine_count=ml_signals.get("prior_quarantine_count"),
            has_prior_quarantine=ml_signals.get("has_prior_quarantine", False),
            has_prior_reject=ml_signals.get("has_prior_reject", False),
            primary_label=ml_signals.get("primary_label"),
            class_probabilities=ml_signals.get("class_probabilities"),
            feature_contributions=feature_contributions,
            model_metadata={},  # Can be populated from ML inference service metadata
        )

        # Regulatory Profile
        regulatory_compliance = (
            policy_profile.regulatory_compliance_json
            if policy_profile and policy_profile.regulatory_compliance_json
            else {}
        )

        control_objectives = []
        if regulatory_compliance:
            for regime, articles in regulatory_compliance.items():
                for article_key, description in articles.items():
                    control_objectives.append({
                        "regime": regime.upper(),
                        "article": article_key,
                        "status": "SUPPORTED_FOR_DEPLOYER",
                        "description": description,
                    })
        else:
            # Default control objectives
            control_objectives = [
                {
                    "regime": "EU_AI_ACT",
                    "article": "12",
                    "status": "SUPPORTED_FOR_DEPLOYER",
                    "description": "Logging and transparency for high-risk AI systems",
                },
                {
                    "regime": "EU_AI_ACT",
                    "article": "13",
                    "status": "SUPPORTED_FOR_DEPLOYER",
                    "description": "Transparency obligations for AI systems",
                },
                {
                    "regime": "EU_DSA",
                    "article": "14",
                    "status": "SUPPORTED_FOR_DEPLOYER",
                    "description": "Systemic risk assessment and mitigation",
                },
            ]

        systemic_risk_tags = []
        if ml_signals.get("synthetic_likelihood", 0) > 60:
            systemic_risk_tags.append("SYNTHETIC_CONTENT")
        if ml_signals.get("has_prior_quarantine", False):
            systemic_risk_tags.append("IDENTITY_FRAUD")
        if ml_signals.get("identity_confidence", 100) < 40:
            systemic_risk_tags.append("LOW_IDENTITY_CONFIDENCE")

        regulatory_profile = RegulatoryProfile(
            applicable_regimes=["EU_AI_ACT", "EU_DSA"],
            control_objectives=control_objectives,
            systemic_risk_tags=systemic_risk_tags,
        )

        # Risk Impact Analysis
        risk_band = self._compute_risk_band(risk_score, policy_profile)
        false_positive_risk, false_negative_risk, expected_harm = self._assess_risk_impact(
            upload.decision, risk_band
        )

        # Build counterfactuals (simplified - without re-running policy engine)
        counterfactuals = []
        if risk_score > 0:
            counterfactual_lower = {
                "scenario": f"risk_score -10 (hypothetical: {risk_score - 10:.1f})",
                "decision": "ALLOW" if risk_score - 10 < 40 else "REVIEW",
                "rationale": "Lower risk score would result in less restrictive decision",
            }
            counterfactuals.append(counterfactual_lower)

        risk_impact_analysis = RiskImpactAnalysis(
            risk_band=risk_band,
            false_positive_risk=false_positive_risk,
            false_negative_risk=false_negative_risk,
            expected_harm_if_misclassified=expected_harm,
            counterfactuals=counterfactuals,
        )

        # Identity and History Context
        historical_consistency = self._compute_historical_consistency(upload)

        identity_history_context = IdentityHistoryContext(
            identity_confidence=ml_signals.get("identity_confidence"),
            shared_device_count=ml_signals.get("shared_device_count"),
            relationship_count=ml_signals.get("relationship_count"),
            prior_quarantine_count=ml_signals.get("prior_quarantine_count"),
            cross_tenant_signals=ml_signals.get("cross_tenant_signals"),
            historical_consistency=historical_consistency,
        )

        # Governance Context
        governance_context = GovernanceContext(
            policy_profile_id=policy_profile.id if policy_profile else None,
            policy_name=policy_profile.name if policy_profile else None,
            policy_last_updated_at=policy_profile.updated_at if policy_profile else None,
            policy_owner=None,  # Can be populated from policy_profile metadata
            human_oversight={
                "required": human_review_required,
                "recommended_role": "content_moderator",
            },
        )

        # Technical Trace Context
        ledger_event_data = {}
        if ledger_event:
            ledger_event_data = {
                "event_hash": ledger_event.event_hash,
                "previous_event_hash": ledger_event.previous_event_hash,
                "event_type": ledger_event.event_type,
                "timestamp": ledger_event.created_at.isoformat() if ledger_event.created_at else None,
            }

        certificate_data = {
            "inputs_hash": certificate.inputs_hash,
            "outputs_hash": certificate.outputs_hash,
            "signature": certificate.signature,
            "algorithm": "RSA-PSS-SHA256",
            "key_fingerprint": None,
        }

        verification_guidance = (
            "To verify this certificate:\n"
            "1. Verify ledger hash chain: check previous_event_hash links to previous event\n"
            "2. Verify certificate signature: use public key to verify signature\n"
            "3. Verify inputs/outputs hashes match certificate data"
        )

        technical_trace_context = TechnicalTraceContext(
            ledger_event=ledger_event_data,
            certificate_data=certificate_data,
            verification_guidance=verification_guidance,
        )

        # Audit Metadata
        audit_metadata = AuditMetadata(
            generated_at=datetime.utcnow(),
            generated_by_version=f"origin-api@{settings.environment}",
            audience=audience,
            redactions={},  # Can be populated based on audience
        )

        # Build EvidencePackV2
        return EvidencePackV2(
            version="origin-evidence-v2",
            tenant=tenant_context,
            certificate=certificate_context,
            upload=upload_context,
            decision_summary=decision_summary,
            ml_and_signals=ml_signals_context,
            regulatory_profile=regulatory_profile,
            risk_impact_analysis=risk_impact_analysis,
            identity_and_history=identity_history_context,
            governance_and_accountability=governance_context,
            technical_trace_and_ledger=technical_trace_context,
            audit_metadata=audit_metadata,
        )

    def _compute_risk_band(self, risk_score: float, policy_profile: Optional[PolicyProfile]) -> str:
        """Compute risk band from risk score and policy thresholds."""
        if not policy_profile or not policy_profile.thresholds_json:
            # Default thresholds
            if risk_score >= 90:
                return "CRITICAL"
            elif risk_score >= 70:
                return "HIGH"
            elif risk_score >= 40:
                return "MEDIUM"
            else:
                return "LOW"

        thresholds = policy_profile.thresholds_json
        reject_threshold = thresholds.get("risk_threshold_reject", 90)
        quarantine_threshold = thresholds.get("risk_threshold_quarantine", 70)
        review_threshold = thresholds.get("risk_threshold_review", 40)

        if risk_score >= reject_threshold:
            return "CRITICAL"
        elif risk_score >= quarantine_threshold:
            return "HIGH"
        elif risk_score >= review_threshold:
            return "MEDIUM"
        else:
            return "LOW"

    def _assess_risk_impact(
        self, decision: str, risk_band: str
    ) -> tuple[str, str, Optional[str]]:
        """Assess false positive/negative risk and expected harm."""
        if decision == "ALLOW":
            false_positive_risk = "LOW" if risk_band == "LOW" else "MEDIUM"
            false_negative_risk = "HIGH" if risk_band in ["HIGH", "CRITICAL"] else "MEDIUM"
            expected_harm = (
                "High: Allowing high-risk content could enable fraud or policy violations"
                if risk_band in ["HIGH", "CRITICAL"]
                else "Low: Low-risk content unlikely to cause harm"
            )
        elif decision == "REJECT":
            false_positive_risk = "HIGH" if risk_band == "LOW" else "MEDIUM"
            false_negative_risk = "LOW"
            expected_harm = (
                "High: Rejecting legitimate content could harm creator reputation"
                if risk_band == "LOW"
                else "Low: Rejecting high-risk content prevents harm"
            )
        else:  # REVIEW, QUARANTINE
            false_positive_risk = "MEDIUM"
            false_negative_risk = "MEDIUM"
            expected_harm = "Moderate: Requires human review to assess actual risk"

        return false_positive_risk, false_negative_risk, expected_harm

    def _compute_historical_consistency(self, upload: Upload) -> Optional[dict]:
        """Compute historical consistency for account/PVID."""
        if not upload.account_id and not upload.pvid:
            return None

        # Query last 90 days
        window_start = upload.received_at - timedelta(days=90)

        query = self.db.query(Upload.decision, func.count(Upload.id).label("count"))
        query = query.filter(
            Upload.tenant_id == upload.tenant_id,
            Upload.received_at >= window_start,
            Upload.id != upload.id,  # Exclude current upload
        )

        if upload.account_id:
            query = query.filter(Upload.account_id == upload.account_id)
        elif upload.pvid:
            query = query.filter(Upload.pvid == upload.pvid)

        results = query.group_by(Upload.decision).all()

        decision_counts = {decision: count for decision, count in results}

        return {
            "last_90_days": decision_counts,
            "total_decisions": sum(decision_counts.values()),
        }

    def generate_pdf(
        self, certificate: DecisionCertificate, upload: Upload, evidence_json: Optional[dict] = None
    ) -> bytes:
        """Generate professionally styled PDF evidence pack (Evidence Pack v2).

        Uses EvidencePackV2 schema to enrich PDF with regulatory compliance information.
        Preserves existing sections for backward compatibility.
        """
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )
        story = []
        styles = getSampleStyleSheet()

        # Build EvidencePackV2 if not provided
        if evidence_json is None:
            evidence_json = self.generate_json(certificate, upload, audience="INTERNAL")
        
        # Parse EvidencePackV2 (may have extra fields for backward compatibility)
        try:
            evidence_v2 = EvidencePackV2.model_validate(evidence_json)
        except Exception:
            # Fallback to old structure if v2 parsing fails
            evidence_v2 = None

        # Custom styles
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontSize=24,
            textColor=colors.HexColor("#1a1a1a"),
            spaceAfter=12,
            alignment=1,  # Center
        )

        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=colors.HexColor("#2c3e50"),
            spaceAfter=12,
            spaceBefore=18,
        )

        decision_color = self._get_decision_color(upload.decision)
        decision_style = ParagraphStyle(
            "DecisionBadge",
            parent=styles["Normal"],
            fontSize=16,
            textColor=colors.HexColor(f"#{decision_color[0]:02x}{decision_color[1]:02x}{decision_color[2]:02x}"),
            fontName="Helvetica-Bold",
            backColor=colors.HexColor("#f8f9fa"),
            borderPadding=8,
        )

        # Page 1 - Executive Summary
        story.append(Paragraph("ORIGIN Decision Certificate", title_style))
        story.append(Spacer(1, 0.1 * inch))

        # Decision Badge
        decision_text = f"<b>Decision: {upload.decision}</b>"
        story.append(Paragraph(decision_text, decision_style))
        story.append(Spacer(1, 0.2 * inch))

        # Gather data (for backward compatibility)
        data = self._gather_evidence_data(certificate, upload)

        # Create cell style for all tables
        cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
            spaceAfter=0,
        )
        
        # Certificate Information Table
        cert_data = [
            [Paragraph("Certificate ID", cell_style), Paragraph(certificate.certificate_id, cell_style)],
            [Paragraph("Issued At", cell_style), Paragraph(certificate.issued_at.strftime("%Y-%m-%d %H:%M:%S UTC"), cell_style)],
            [Paragraph("Policy Version", cell_style), Paragraph(certificate.policy_version, cell_style)],
        ]
        cert_table = Table(cert_data, colWidths=[2 * inch, 4.5 * inch])
        cert_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#495057")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                ]
            )
        )
        story.append(Paragraph("<b>Certificate Information</b>", heading_style))
        story.append(cert_table)
        story.append(Spacer(1, 0.2 * inch))

        # Decision Explanation
        explanation = self._get_decision_explanation(
            upload.decision, data["decision_trace"].get("rationale")
        )
        story.append(Paragraph("<b>Decision Explanation</b>", heading_style))
        story.append(Paragraph(explanation, styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))
        
        # Add EvidencePackV2 enhancements if available
        if evidence_v2:
            # Decision Summary with rationale
            if evidence_v2.decision_summary.decision_rationale:
                story.append(Paragraph("<b>Decision Rationale</b>", heading_style))
                story.append(Paragraph(evidence_v2.decision_summary.decision_rationale, styles["Normal"]))
                story.append(Spacer(1, 0.2 * inch))
            
            # Regulatory Profile (if applicable regimes present)
            if evidence_v2.regulatory_profile.applicable_regimes:
                story.append(Paragraph("<b>Regulatory Compliance</b>", heading_style))
                regimes_text = ", ".join(evidence_v2.regulatory_profile.applicable_regimes)
                story.append(Paragraph(f"Applicable Regimes: {regimes_text}", styles["Normal"]))
                if evidence_v2.regulatory_profile.control_objectives:
                    story.append(Paragraph("Control Objectives:", styles["Normal"]))
                    for obj in evidence_v2.regulatory_profile.control_objectives[:3]:  # Show first 3
                        obj_text = f"• {obj.get('regime', '')} Art. {obj.get('article', '')}: {obj.get('description', '')[:80]}..."
                        story.append(Paragraph(obj_text, styles["Normal"]))
                story.append(Spacer(1, 0.2 * inch))

        # Upload Information
        upload_data = [
            [Paragraph("Ingestion ID", cell_style), Paragraph(upload.ingestion_id, cell_style)],
            [Paragraph("External ID", cell_style), Paragraph(upload.external_id, cell_style)],
            [Paragraph("Title", cell_style), Paragraph(upload.title or "N/A", cell_style)],
            [Paragraph("PVID", cell_style), Paragraph(upload.pvid or "N/A", cell_style)],
            [Paragraph("Received At", cell_style), Paragraph(upload.received_at.strftime("%Y-%m-%d %H:%M:%S UTC"), cell_style)],
        ]
        if upload.content_ref:
            content_ref_text = upload.content_ref[:80] + "..." if len(upload.content_ref) > 80 else upload.content_ref
            upload_data.append([Paragraph("Content Reference", cell_style), Paragraph(content_ref_text, cell_style)])

        upload_table = Table(upload_data, colWidths=[2 * inch, 4.5 * inch])
        upload_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#495057")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                ]
            )
        )
        story.append(Paragraph("<b>Upload Information</b>", heading_style))
        story.append(upload_table)
        story.append(Spacer(1, 0.2 * inch))

        # Account Information
        if data["account"]:
            account_data = [
                [Paragraph("External ID", cell_style), Paragraph(data["account"].external_id, cell_style)],
                [Paragraph("Type", cell_style), Paragraph(data["account"].type, cell_style)],
                [Paragraph("Display Name", cell_style), Paragraph(data["account"].display_name or "N/A", cell_style)],
                [Paragraph("Risk State", cell_style), Paragraph(data["account"].risk_state, cell_style)],
            ]
            if data["account"].created_at:
                account_data.append([
                    Paragraph("Account Created", cell_style),
                    Paragraph(data["account"].created_at.strftime("%Y-%m-%d %H:%M:%S UTC"), cell_style)
                ])

            account_table = Table(account_data, colWidths=[2 * inch, 4.5 * inch])
            account_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#495057")),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                    ]
                )
            )
            story.append(Paragraph("<b>Account Information</b>", heading_style))
            story.append(account_table)
            story.append(Spacer(1, 0.2 * inch))

        # Risk Scores Table - Use Paragraph objects for text wrapping
        risk_score = float(upload.risk_score) if upload.risk_score else 0
        assurance_score = float(upload.assurance_score) if upload.assurance_score else 0

        ml_signals = data["decision_trace"].get("ml_signals", {})
        
        scores_data = [
            [
                Paragraph("<b>Metric</b>", styles["Normal"]),
                Paragraph("<b>Score</b>", styles["Normal"]),
                Paragraph("<b>Interpretation</b>", styles["Normal"]),
            ],
            [
                Paragraph("Risk Score", cell_style),
                Paragraph(f"{risk_score:.2f}/100", cell_style),
                Paragraph(
                    "Higher = more risky. Based on ML model predictions weighted by severity.",
                    cell_style,
                ),
            ],
            [
                Paragraph("Assurance Score", cell_style),
                Paragraph(f"{assurance_score:.2f}/100", cell_style),
                Paragraph(
                    "Higher = more confident/legitimate. Derived from probability distribution confidence.",
                    cell_style,
                ),
            ],
        ]

        if ml_signals.get("anomaly_score") is not None:
            anomaly = float(ml_signals["anomaly_score"])
            scores_data.append(
                [
                    Paragraph("Anomaly Score", cell_style),
                    Paragraph(f"{anomaly:.2f}/100", cell_style),
                    Paragraph(
                        "Lower = more anomalous. Trained on normal/ALLOW behavior patterns.",
                        cell_style,
                    ),
                ]
            )

        if ml_signals.get("synthetic_likelihood") is not None:
            synthetic = float(ml_signals["synthetic_likelihood"])
            scores_data.append(
                [
                    Paragraph("Synthetic Likelihood", cell_style),
                    Paragraph(f"{synthetic:.2f}/100", cell_style),
                    Paragraph(
                        "Higher = more likely AI-generated. Heuristic detection of synthetic content.",
                        cell_style,
                    ),
                ]
            )

        if ml_signals.get("identity_confidence") is not None:
            identity = float(ml_signals["identity_confidence"])
            scores_data.append(
                [
                    Paragraph("Identity Confidence", cell_style),
                    Paragraph(f"{identity:.2f}/100", cell_style),
                    Paragraph(
                        "Higher = more established identity. Based on graph features and history.",
                        cell_style,
                    ),
                ]
            )

        # Adjust column widths to fit page (letter width 8.5" - margins 1.5" = 7" usable)
        # Use: 2" for metric, 1.2" for score, 3.6" for interpretation
        scores_table = Table(scores_data, colWidths=[2 * inch, 1.2 * inch, 3.6 * inch])
        scores_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ]
            )
        )
        story.append(Paragraph("<b>Risk Assessment Scores</b>", heading_style))
        story.append(scores_table)
        story.append(Spacer(1, 0.2 * inch))

        # Decision Rationale
        if data["decision_trace"].get("rationale"):
            story.append(Paragraph("<b>Decision Rationale</b>", heading_style))
            story.append(Paragraph(data["decision_trace"]["rationale"], styles["Normal"]))
            story.append(Spacer(1, 0.2 * inch))

        # Triggered Rules and Reason Codes
        if data["decision_trace"].get("triggered_rules") or data["decision_trace"].get("reason_codes"):
            story.append(Paragraph("<b>Policy Evaluation Details</b>", heading_style))
            
            if data["decision_trace"].get("triggered_rules"):
                story.append(Paragraph("<b>Triggered Rules:</b>", styles["Normal"]))
                for rule in data["decision_trace"]["triggered_rules"]:
                    story.append(Paragraph(f"• {rule}", styles["Normal"]))
                story.append(Spacer(1, 0.1 * inch))

            if data["decision_trace"].get("reason_codes"):
                story.append(Paragraph("<b>Reason Codes:</b>", styles["Normal"]))
                for code in data["decision_trace"]["reason_codes"]:
                    story.append(Paragraph(f"• {code}", styles["Normal"]))
            story.append(Spacer(1, 0.2 * inch))

        # ML Model Predictions
        if ml_signals.get("primary_label") or ml_signals.get("class_probabilities"):
            story.append(Paragraph("<b>ML Model Predictions</b>", heading_style))
            ml_data = []
            if ml_signals.get("primary_label"):
                ml_data.append([
                    Paragraph("Primary Label", cell_style),
                    Paragraph(ml_signals["primary_label"], cell_style)
                ])
            if ml_signals.get("class_probabilities"):
                ml_data.append([
                    Paragraph("Class Probabilities", cell_style),
                    Paragraph("", cell_style)
                ])
                for label, prob in ml_signals["class_probabilities"].items():
                    ml_data.append([
                        Paragraph("", cell_style),
                        Paragraph(f"{label}: {float(prob)*100:.1f}%", cell_style)
                    ])

            if ml_data:
                ml_table = Table(ml_data, colWidths=[2 * inch, 4.5 * inch])
                ml_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#495057")),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 10),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                        ]
                    )
                )
                story.append(ml_table)
            story.append(Spacer(1, 0.2 * inch))

        # Policy Thresholds - Use Paragraph objects for text wrapping
        if data["policy_profile"] and data["policy_profile"].thresholds_json:
            story.append(Paragraph("<b>Policy Thresholds</b>", heading_style))
            thresholds = data["policy_profile"].thresholds_json
            threshold_data = [
                [
                    Paragraph("<b>Threshold</b>", styles["Normal"]),
                    Paragraph("<b>Value</b>", styles["Normal"]),
                    Paragraph("<b>Description</b>", styles["Normal"]),
                ]
            ]
            threshold_descriptions = {
                "risk_threshold_review": "Risk score above which content requires review",
                "risk_threshold_quarantine": "Risk score above which content is quarantined",
                "risk_threshold_reject": "Risk score above which content is rejected",
                "anomaly_threshold": "Anomaly score below which behavior is considered anomalous",
                "synthetic_threshold": "Synthetic likelihood above which content is flagged",
                "assurance_threshold_allow": "Assurance score above which low-risk content can be allowed",
            }
            for key, value in thresholds.items():
                threshold_data.append([
                    Paragraph(key.replace("_", " ").title(), cell_style),
                    Paragraph(str(value), cell_style),
                    Paragraph(threshold_descriptions.get(key, ""), cell_style),
                ])

            # Adjust column widths: 2.2" for threshold, 1" for value, 3.6" for description
            threshold_table = Table(threshold_data, colWidths=[2.2 * inch, 1 * inch, 3.6 * inch])
            threshold_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                    ]
                )
            )
            story.append(threshold_table)
            story.append(Spacer(1, 0.2 * inch))

        # Governance Integrity
        story.append(PageBreak())
        story.append(Paragraph("<b>Governance Integrity</b>", heading_style))
        
        # Create a style for hash/signature text (monospace, smaller)
        hash_style = ParagraphStyle(
            "HashStyle",
            parent=cell_style,
            fontName="Courier",
            fontSize=8,
            leading=10,
        )
        
        integrity_data = [
            [Paragraph("Ledger Hash", cell_style), Paragraph(certificate.ledger_hash, hash_style)],
            [Paragraph("Inputs Hash", cell_style), Paragraph(certificate.inputs_hash, hash_style)],
            [Paragraph("Outputs Hash", cell_style), Paragraph(certificate.outputs_hash, hash_style)],
            [Paragraph("Signature", cell_style), Paragraph(certificate.signature[:80] + "...", hash_style)],
        ]
        integrity_table = Table(integrity_data, colWidths=[2 * inch, 4.5 * inch])
        integrity_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#495057")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                ]
            )
        )
        story.append(integrity_table)

        doc.build(story)
        return buffer.getvalue()

    def generate_html(self, certificate: DecisionCertificate, upload: Upload) -> str:
        """Generate professionally styled HTML evidence pack."""
        data = self._gather_evidence_data(certificate, upload)
        
        decision_color = self._get_decision_color(upload.decision)
        decision_color_hex = f"#{decision_color[0]:02x}{decision_color[1]:02x}{decision_color[2]:02x}"
        
        ml_signals = data["decision_trace"].get("ml_signals", {})
        risk_score = float(upload.risk_score) if upload.risk_score else 0
        assurance_score = float(upload.assurance_score) if upload.assurance_score else 0
        
        template_str = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ORIGIN Decision Certificate - {{ certificate_id }}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #2c3e50;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #1a1a1a 0%, #2c3e50 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
        }
        
        .header p {
            opacity: 0.9;
            font-size: 1.1em;
        }
        
        .decision-badge {
            display: inline-block;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 1.5em;
            font-weight: 700;
            margin: 20px 0;
            background: {{ decision_color }};
            color: white;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        }
        
        .content {
            padding: 40px;
        }
        
        .section {
            margin-bottom: 40px;
        }
        
        .section-title {
            font-size: 1.8em;
            color: #2c3e50;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
        }
        
        .card {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            border-left: 4px solid #667eea;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }
        
        .info-grid {
            display: grid;
            grid-template-columns: 200px 1fr;
            gap: 15px;
            margin-bottom: 15px;
        }
        
        .info-label {
            font-weight: 700;
            color: #495057;
        }
        
        .info-value {
            color: #212529;
            word-break: break-word;
        }
        
        .hash {
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
            background: #e9ecef;
            padding: 8px;
            border-radius: 4px;
            word-break: break-all;
        }
        
        .scores-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .score-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            border-top: 4px solid #667eea;
        }
        
        .score-label {
            font-size: 0.9em;
            color: #6c757d;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }
        
        .score-value {
            font-size: 2em;
            font-weight: 700;
            color: #2c3e50;
            margin-bottom: 8px;
        }
        
        .score-interpretation {
            font-size: 0.85em;
            color: #6c757d;
            line-height: 1.4;
        }
        
        .explanation-box {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 8px;
            padding: 25px;
            margin: 20px 0;
            border-left: 4px solid #667eea;
        }
        
        .explanation-box p {
            font-size: 1.05em;
            line-height: 1.8;
            color: #495057;
        }
        
        .rules-list, .codes-list {
            list-style: none;
            padding: 0;
        }
        
        .rules-list li, .codes-list li {
            background: white;
            padding: 12px 15px;
            margin-bottom: 8px;
            border-radius: 6px;
            border-left: 3px solid #667eea;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }
        
        .table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }
        
        .table thead {
            background: #2c3e50;
            color: white;
        }
        
        .table th {
            padding: 15px;
            text-align: left;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85em;
            letter-spacing: 0.5px;
        }
        
        .table td {
            padding: 12px 15px;
            border-bottom: 1px solid #e9ecef;
        }
        
        .table tbody tr:hover {
            background: #f8f9fa;
        }
        
        .table tbody tr:last-child td {
            border-bottom: none;
        }
        
        .probabilities {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 15px;
        }
        
        .probability-badge {
            background: white;
            padding: 10px 20px;
            border-radius: 20px;
            border: 2px solid #667eea;
            font-weight: 600;
            color: #2c3e50;
        }
        
        .integrity-section {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 25px;
            margin-top: 40px;
        }
        
        .footer {
            background: #2c3e50;
            color: white;
            padding: 20px;
            text-align: center;
            font-size: 0.9em;
        }
        
        @media (max-width: 768px) {
            .info-grid {
                grid-template-columns: 1fr;
            }
            
            .scores-grid {
                grid-template-columns: 1fr;
            }
            
            .header h1 {
                font-size: 1.8em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>ORIGIN Decision Certificate</h1>
            <p>Tamper-Evident Decision Documentation</p>
            <div class="decision-badge">{{ decision }}</div>
        </div>
        
        <div class="content">
            <!-- Decision Explanation -->
            <div class="section">
                <h2 class="section-title">Decision Explanation</h2>
                <div class="explanation-box">
                    <p>{{ explanation }}</p>
                </div>
            </div>
            
            <!-- Certificate Information -->
            <div class="section">
                <h2 class="section-title">Certificate Information</h2>
                <div class="card">
                    <div class="info-grid">
                        <div class="info-label">Certificate ID</div>
                        <div class="info-value">{{ certificate_id }}</div>
                        <div class="info-label">Issued At</div>
                        <div class="info-value">{{ issued_at }}</div>
                        <div class="info-label">Policy Version</div>
                        <div class="info-value">{{ policy_version }}</div>
                    </div>
                </div>
            </div>
            
            <!-- Upload Information -->
            <div class="section">
                <h2 class="section-title">Upload Information</h2>
                <div class="card">
                    <div class="info-grid">
                        <div class="info-label">Ingestion ID</div>
                        <div class="info-value">{{ ingestion_id }}</div>
                        <div class="info-label">External ID</div>
                        <div class="info-value">{{ external_id }}</div>
                        {% if title %}
                        <div class="info-label">Title</div>
                        <div class="info-value">{{ title }}</div>
                        {% endif %}
                        <div class="info-label">PVID</div>
                        <div class="info-value">{{ pvid }}</div>
                        <div class="info-label">Received At</div>
                        <div class="info-value">{{ received_at }}</div>
                        {% if content_ref %}
                        <div class="info-label">Content Reference</div>
                        <div class="info-value">{{ content_ref }}</div>
                        {% endif %}
                    </div>
                </div>
            </div>
            
            {% if account %}
            <!-- Account Information -->
            <div class="section">
                <h2 class="section-title">Account Information</h2>
                <div class="card">
                    <div class="info-grid">
                        <div class="info-label">External ID</div>
                        <div class="info-value">{{ account.external_id }}</div>
                        <div class="info-label">Type</div>
                        <div class="info-value">{{ account.type }}</div>
                        {% if account.display_name %}
                        <div class="info-label">Display Name</div>
                        <div class="info-value">{{ account.display_name }}</div>
                        {% endif %}
                        <div class="info-label">Risk State</div>
                        <div class="info-value">{{ account.risk_state }}</div>
                        {% if account.created_at %}
                        <div class="info-label">Account Created</div>
                        <div class="info-value">{{ account.created_at }}</div>
                        {% endif %}
                    </div>
                </div>
            </div>
            {% endif %}
            
            <!-- Risk Assessment Scores -->
            <div class="section">
                <h2 class="section-title">Risk Assessment Scores</h2>
                <div class="scores-grid">
                    <div class="score-card">
                        <div class="score-label">Risk Score</div>
                        <div class="score-value">{{ risk_score }}/100</div>
                        <div class="score-interpretation">
                            Higher = more risky. Based on ML model predictions weighted by severity.
                        </div>
                    </div>
                    <div class="score-card">
                        <div class="score-label">Assurance Score</div>
                        <div class="score-value">{{ assurance_score }}/100</div>
                        <div class="score-interpretation">
                            Higher = more confident/legitimate. Derived from probability distribution confidence.
                        </div>
                    </div>
                    {% if ml_signals.anomaly_score is defined %}
                    <div class="score-card">
                        <div class="score-label">Anomaly Score</div>
                        <div class="score-value">{{ ml_signals.anomaly_score }}/100</div>
                        <div class="score-interpretation">
                            Lower = more anomalous. Trained on normal/ALLOW behavior patterns.
                        </div>
                    </div>
                    {% endif %}
                    {% if ml_signals.synthetic_likelihood is defined %}
                    <div class="score-card">
                        <div class="score-label">Synthetic Likelihood</div>
                        <div class="score-value">{{ ml_signals.synthetic_likelihood }}/100</div>
                        <div class="score-interpretation">
                            Higher = more likely AI-generated. Heuristic detection of synthetic content.
                        </div>
                    </div>
                    {% endif %}
                    {% if ml_signals.identity_confidence is defined %}
                    <div class="score-card">
                        <div class="score-label">Identity Confidence</div>
                        <div class="score-value">{{ ml_signals.identity_confidence }}/100</div>
                        <div class="score-interpretation">
                            Higher = more established identity. Based on graph features and history.
                        </div>
                    </div>
                    {% endif %}
                </div>
            </div>
            
            {% if rationale %}
            <!-- Decision Rationale -->
            <div class="section">
                <h2 class="section-title">Decision Rationale</h2>
                <div class="card">
                    <p>{{ rationale }}</p>
                </div>
            </div>
            {% endif %}
            
            {% if triggered_rules or reason_codes %}
            <!-- Policy Evaluation Details -->
            <div class="section">
                <h2 class="section-title">Policy Evaluation Details</h2>
                {% if triggered_rules %}
                <div class="card">
                    <h3 style="margin-bottom: 15px; color: #2c3e50;">Triggered Rules</h3>
                    <ul class="rules-list">
                        {% for rule in triggered_rules %}
                        <li>{{ rule }}</li>
                        {% endfor %}
                    </ul>
                </div>
                {% endif %}
                {% if reason_codes %}
                <div class="card">
                    <h3 style="margin-bottom: 15px; color: #2c3e50;">Reason Codes</h3>
                    <ul class="codes-list">
                        {% for code in reason_codes %}
                        <li>{{ code }}</li>
                        {% endfor %}
                    </ul>
                </div>
                {% endif %}
            </div>
            {% endif %}
            
            {% if ml_signals.primary_label or ml_signals.class_probabilities %}
            <!-- ML Model Predictions -->
            <div class="section">
                <h2 class="section-title">ML Model Predictions</h2>
                <div class="card">
                    {% if ml_signals.primary_label %}
                    <div class="info-grid">
                        <div class="info-label">Primary Label</div>
                        <div class="info-value">{{ ml_signals.primary_label }}</div>
                    </div>
                    {% endif %}
                    {% if ml_signals.class_probabilities %}
                    <div style="margin-top: 15px;">
                        <div class="info-label" style="margin-bottom: 10px;">Class Probabilities</div>
                        <div class="probabilities">
                            {% for label, prob in ml_signals.class_probabilities.items() %}
                            <div class="probability-badge">{{ label }}: {{ (prob * 100)|round(1) }}%</div>
                            {% endfor %}
                        </div>
                    </div>
                    {% endif %}
                </div>
            </div>
            {% endif %}
            
            {% if thresholds %}
            <!-- Policy Thresholds -->
            <div class="section">
                <h2 class="section-title">Policy Thresholds</h2>
                <table class="table">
                    <thead>
                        <tr>
                            <th>Threshold</th>
                            <th>Value</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for key, value in thresholds.items() %}
                        <tr>
                            <td><strong>{{ key.replace('_', ' ').title() }}</strong></td>
                            <td>{{ value }}</td>
                            <td>{{ threshold_descriptions.get(key, '') }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endif %}
            
            <!-- Governance Integrity -->
            <div class="integrity-section">
                <h2 class="section-title" style="border-bottom-color: #2c3e50;">Governance Integrity</h2>
                <div class="info-grid">
                    <div class="info-label">Ledger Hash</div>
                    <div class="hash">{{ ledger_hash }}</div>
                    <div class="info-label">Inputs Hash</div>
                    <div class="hash">{{ inputs_hash }}</div>
                    <div class="info-label">Outputs Hash</div>
                    <div class="hash">{{ outputs_hash }}</div>
                    <div class="info-label">Signature</div>
                    <div class="hash">{{ signature }}</div>
                </div>
            </div>
        </div>
        
        <div class="footer">
            <p>This certificate is tamper-evident and cryptographically signed. Any modification will invalidate the signature.</p>
            <p style="margin-top: 10px; opacity: 0.8;">Generated by ORIGIN Decision Governance System</p>
        </div>
    </div>
</body>
</html>
        """

        # Prepare threshold descriptions
        threshold_descriptions = {
            "risk_threshold_review": "Risk score above which content requires review",
            "risk_threshold_quarantine": "Risk score above which content is quarantined",
            "risk_threshold_reject": "Risk score above which content is rejected",
            "anomaly_threshold": "Anomaly score below which behavior is considered anomalous",
            "synthetic_threshold": "Synthetic likelihood above which content is flagged",
            "assurance_threshold_allow": "Assurance score above which low-risk content can be allowed",
        }

        template = Template(template_str)
        return template.render(
            certificate_id=certificate.certificate_id,
            issued_at=certificate.issued_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            decision=upload.decision,
            decision_color=decision_color_hex,
            explanation=self._get_decision_explanation(
                upload.decision, data["decision_trace"].get("rationale")
            ),
            policy_version=certificate.policy_version,
            ingestion_id=upload.ingestion_id,
            external_id=upload.external_id,
            title=upload.title,
            pvid=upload.pvid or "N/A",
            received_at=upload.received_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            content_ref=upload.content_ref,
            account=data["account"],
            risk_score=f"{risk_score:.2f}",
            assurance_score=f"{assurance_score:.2f}",
            ml_signals=ml_signals,
            rationale=data["decision_trace"].get("rationale"),
            triggered_rules=data["decision_trace"].get("triggered_rules", []),
            reason_codes=data["decision_trace"].get("reason_codes", []),
            thresholds=(
                data["policy_profile"].thresholds_json
                if data["policy_profile"] and data["policy_profile"].thresholds_json
                else {}
            ),
            threshold_descriptions=threshold_descriptions,
            ledger_hash=certificate.ledger_hash,
            inputs_hash=certificate.inputs_hash,
            outputs_hash=certificate.outputs_hash,
            signature=certificate.signature,
        )

    def save_artifacts(
        self, certificate_id: str, formats: list[str], artifacts: dict
    ) -> dict:
        """Save artifacts to storage and return storage references."""
        storage_refs = {}
        cert_dir = self.storage_base / certificate_id
        cert_dir.mkdir(parents=True, exist_ok=True)

        for fmt in formats:
            if fmt == "json" and "json" in artifacts:
                path = cert_dir / "evidence.json"
                with open(path, "w") as f:
                    json.dump(artifacts["json"], f, indent=2)
                storage_refs["json"] = str(path)

            elif fmt == "pdf" and "pdf" in artifacts:
                path = cert_dir / "evidence.pdf"
                with open(path, "wb") as f:
                    f.write(artifacts["pdf"])
                storage_refs["pdf"] = str(path)

            elif fmt == "html" and "html" in artifacts:
                path = cert_dir / "evidence.html"
                with open(path, "w") as f:
                    f.write(artifacts["html"])
                storage_refs["html"] = str(path)

        return storage_refs

