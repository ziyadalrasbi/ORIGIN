"""Webhook management routes."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.models import Webhook, WebhookDelivery
from origin_api.models.tenant import Tenant
from origin_api.webhooks.service import WebhookService

router = APIRouter(prefix="/v1", tags=["webhooks"])
logger = logging.getLogger(__name__)


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
    correlation_id = getattr(request.state, "correlation_id", None)

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

    logger.info(
        "Webhook created",
        extra={
            "tenant_id": tenant.id,
            "correlation_id": correlation_id,
            "webhook_id": webhook.id,
        },
    )

    return webhook


@router.post("/webhooks/test", status_code=status.HTTP_200_OK)
async def test_webhook(
    webhook_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Test webhook delivery."""
    tenant: Tenant = request.state.tenant
    correlation_id = getattr(request.state, "correlation_id", None)

    webhook = (
        db.query(Webhook)
        .filter(Webhook.tenant_id == tenant.id, Webhook.id == webhook_id)
        .first()
    )

    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Enqueue test event (async)
    try:
        from origin_worker.tasks import deliver_webhook
        deliver_webhook.delay(
            webhook.id,
            "test",
            {
                "message": "Test webhook from ORIGIN",
                "timestamp": datetime.utcnow().isoformat(),
                "correlation_id": correlation_id,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to enqueue webhook test: {e}")
        # Fallback to sync
        service = WebhookService(db)
        service.deliver_webhook(
            tenant.id,
            "test",
            {"message": "Test webhook from ORIGIN", "timestamp": datetime.utcnow().isoformat()},
        )

    return {"status": "sent", "webhook_id": webhook_id}


@router.get("/webhooks/{webhook_id}/deliveries")
async def get_webhook_deliveries(
    webhook_id: int,
    request: Request,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get webhook delivery history."""
    tenant: Tenant = request.state.tenant

    webhook = (
        db.query(Webhook)
        .filter(Webhook.tenant_id == tenant.id, Webhook.id == webhook_id)
        .first()
    )

    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    deliveries = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "webhook_id": webhook_id,
        "deliveries": [
            {
                "id": d.id,
                "event_type": d.event_type,
                "status": d.status,
                "attempt_number": d.attempt_number,
                "response_status": d.response_status,
                "created_at": d.created_at.isoformat(),
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            }
            for d in deliveries
        ],
    }
