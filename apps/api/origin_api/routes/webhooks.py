"""Webhook management routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.models import Webhook
from origin_api.models.tenant import Tenant
from origin_api.webhooks.service import WebhookService

router = APIRouter(prefix="/v1", tags=["webhooks"])


class WebhookCreate(BaseModel):
    """Webhook creation request."""

    url: str
    secret: str
    events: list[str]  # ["decision.created", "decision.updated", etc.]


class WebhookResponse(BaseModel):
    """Webhook response."""

    id: int
    url: str
    events: list[str]
    enabled: bool

    class Config:
        from_attributes = True


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    webhook_data: WebhookCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a webhook."""
    tenant: Tenant = request.state.tenant

    # Hash secret
    import hashlib
    secret_hash = hashlib.sha256(webhook_data.secret.encode()).hexdigest()

    webhook = Webhook(
        tenant_id=tenant.id,
        url=webhook_data.url,
        secret_hash=secret_hash,
        events=webhook_data.events,
        enabled=True,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    return webhook


@router.post("/webhooks/test", status_code=status.HTTP_200_OK)
async def test_webhook(
    webhook_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Test webhook delivery."""
    tenant: Tenant = request.state.tenant

    webhook = (
        db.query(Webhook)
        .filter(Webhook.tenant_id == tenant.id, Webhook.id == webhook_id)
        .first()
    )

    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Send test event
    service = WebhookService(db)
    service.deliver_webhook(
        tenant.id,
        "test",
        {"message": "Test webhook from ORIGIN", "timestamp": datetime.utcnow().isoformat()},
    )

    return {"status": "sent", "webhook_id": webhook_id}

