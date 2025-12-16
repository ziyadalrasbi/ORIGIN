"""Evidence pack generation service."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Template
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from sqlalchemy.orm import Session

from origin_api.models import DecisionCertificate, EvidencePack, Upload
from origin_api.settings import get_settings

settings = get_settings()


class EvidencePackGenerator:
    """Generate evidence packs in multiple formats."""

    def __init__(self, db: Session):
        """Initialize evidence pack generator."""
        self.db = db
        self.storage_base = Path("evidence_packs")  # Local storage for dev

    def generate_json(self, certificate: DecisionCertificate, upload: Upload) -> dict:
        """Generate JSON evidence pack."""
        evidence = {
            "certificate_id": certificate.certificate_id,
            "issued_at": certificate.issued_at.isoformat(),
            "decision": upload.decision,
            "policy_version": certificate.policy_version,
            "inputs_hash": certificate.inputs_hash,
            "outputs_hash": certificate.outputs_hash,
            "ledger_hash": certificate.ledger_hash,
            "signature": certificate.signature,
            "upload": {
                "ingestion_id": upload.ingestion_id,
                "external_id": upload.external_id,
                "received_at": upload.received_at.isoformat(),
                "pvid": upload.pvid,
            },
            "scores": {
                "risk_score": float(upload.risk_score) if upload.risk_score else None,
                "assurance_score": float(upload.assurance_score) if upload.assurance_score else None,
            },
        }
        return evidence

    def generate_pdf(self, certificate: DecisionCertificate, upload: Upload) -> bytes:
        """Generate PDF evidence pack."""
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        story = []
        styles = getSampleStyleSheet()

        # Title
        story.append(Paragraph("ORIGIN Decision Certificate", styles["Title"]))
        story.append(Spacer(1, 0.2 * inch))

        # Certificate Info
        story.append(Paragraph(f"<b>Certificate ID:</b> {certificate.certificate_id}", styles["Normal"]))
        story.append(Paragraph(f"<b>Issued At:</b> {certificate.issued_at.isoformat()}", styles["Normal"]))
        story.append(Paragraph(f"<b>Decision:</b> {upload.decision}", styles["Normal"]))
        story.append(Paragraph(f"<b>Policy Version:</b> {certificate.policy_version}", styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))

        # Upload Info
        story.append(Paragraph("<b>Upload Information</b>", styles["Heading2"]))
        story.append(Paragraph(f"Ingestion ID: {upload.ingestion_id}", styles["Normal"]))
        story.append(Paragraph(f"External ID: {upload.external_id}", styles["Normal"]))
        story.append(Paragraph(f"PVID: {upload.pvid or 'N/A'}", styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))

        # Scores
        story.append(Paragraph("<b>Risk Signals</b>", styles["Heading2"]))
        story.append(Paragraph(f"Risk Score: {upload.risk_score or 'N/A'}", styles["Normal"]))
        story.append(Paragraph(f"Assurance Score: {upload.assurance_score or 'N/A'}", styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))

        # Integrity
        story.append(Paragraph("<b>Governance Integrity</b>", styles["Heading2"]))
        story.append(Paragraph(f"Ledger Hash: {certificate.ledger_hash}", styles["Normal"]))
        story.append(Paragraph(f"Inputs Hash: {certificate.inputs_hash}", styles["Normal"]))
        story.append(Paragraph(f"Outputs Hash: {certificate.outputs_hash}", styles["Normal"]))
        story.append(Paragraph(f"Signature: {certificate.signature[:50]}...", styles["Normal"]))

        doc.build(story)
        return buffer.getvalue()

    def generate_html(self, certificate: DecisionCertificate, upload: Upload) -> str:
        """Generate HTML evidence pack."""
        template_str = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>ORIGIN Decision Certificate - {{ certificate_id }}</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                h2 { color: #666; margin-top: 30px; }
                .info { background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 10px 0; }
                .hash { font-family: monospace; font-size: 0.9em; word-break: break-all; }
            </style>
        </head>
        <body>
            <h1>ORIGIN Decision Certificate</h1>
            <div class="info">
                <p><strong>Certificate ID:</strong> {{ certificate_id }}</p>
                <p><strong>Issued At:</strong> {{ issued_at }}</p>
                <p><strong>Decision:</strong> {{ decision }}</p>
                <p><strong>Policy Version:</strong> {{ policy_version }}</p>
            </div>
            
            <h2>Upload Information</h2>
            <div class="info">
                <p><strong>Ingestion ID:</strong> {{ ingestion_id }}</p>
                <p><strong>External ID:</strong> {{ external_id }}</p>
                <p><strong>PVID:</strong> {{ pvid }}</p>
            </div>
            
            <h2>Risk Signals</h2>
            <div class="info">
                <p><strong>Risk Score:</strong> {{ risk_score }}</p>
                <p><strong>Assurance Score:</strong> {{ assurance_score }}</p>
            </div>
            
            <h2>Governance Integrity</h2>
            <div class="info">
                <p><strong>Ledger Hash:</strong> <span class="hash">{{ ledger_hash }}</span></p>
                <p><strong>Inputs Hash:</strong> <span class="hash">{{ inputs_hash }}</span></p>
                <p><strong>Outputs Hash:</strong> <span class="hash">{{ outputs_hash }}</span></p>
                <p><strong>Signature:</strong> <span class="hash">{{ signature }}</span></p>
            </div>
        </body>
        </html>
        """

        template = Template(template_str)
        return template.render(
            certificate_id=certificate.certificate_id,
            issued_at=certificate.issued_at.isoformat(),
            decision=upload.decision,
            policy_version=certificate.policy_version,
            ingestion_id=upload.ingestion_id,
            external_id=upload.external_id,
            pvid=upload.pvid or "N/A",
            risk_score=upload.risk_score or "N/A",
            assurance_score=upload.assurance_score or "N/A",
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

