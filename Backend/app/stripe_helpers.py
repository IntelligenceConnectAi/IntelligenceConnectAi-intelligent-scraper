"""
Shared Stripe read helpers — used by both the client-facing billing router
(app/routers/billing.py) and the admin Clients Management refund flow
(app/routers/admin_clients.py), so the invoice → InvoiceResponse mapping can't
drift between the two.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import stripe

from app.config import settings
from app.schemas import InvoiceResponse

log = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key


async def list_stripe_invoices(customer_id: str, *, limit: int = 12) -> list[InvoiceResponse]:
    try:
        invoices = stripe.Invoice.list(customer=customer_id, limit=limit)
    except stripe.error.StripeError as e:
        log.error(f"Stripe invoice list failed for {customer_id}: {e}")
        return []
    return [
        InvoiceResponse(
            id=inv["id"],
            amount_paid=Decimal(inv["amount_paid"]) / 100,
            currency=inv["currency"],
            status=inv["status"],
            created_at=datetime.fromtimestamp(inv["created"], tz=timezone.utc),
            invoice_pdf=inv.get("invoice_pdf"),
            hosted_invoice_url=inv.get("hosted_invoice_url"),
        )
        for inv in invoices["data"]
    ]
