"""
NEXUS ERP — n8n Automation Bridge
Fires the two n8n workflows described in N8N_AUTOMATION_WIRING.md and stored
in blockchain-module-main/n8n-workflows/:
  - vendor-reorder-email          — itemized bill + Accept/Reject buttons
  - vendor-contract-confirmation  — sent after the vendor accepts, with a
    copy of the now-executed smart contract / bill
Does not build the invoice or the smart contract itself — those come from
invoice_service.py / contract_service.py unchanged; this module only shapes
the webhook payloads and posts them.

Dev mode (webhook URL unset): prints the payload instead of posting,
matching the same graceful-fallback pattern email_service.py already uses
for SMTP.
"""
import os
import httpx
from dotenv import load_dotenv
from fastapi.encoders import jsonable_encoder

import email_service

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_CONTRACT_CONFIRMATION_WEBHOOK_URL = os.getenv("N8N_CONTRACT_CONFIRMATION_WEBHOOK_URL", "")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "")

# Phase 2 — vendor_orders flow (distinct from the Phase 1 auto-reorder
# webhooks above; see n8n-workflows/vendor-order-*.workflow.json).
N8N_VENDOR_ORDER_WEBHOOK_URL = os.getenv("N8N_VENDOR_ORDER_WEBHOOK_URL", "")
N8N_VENDOR_ORDER_SHIPMENT_LINK_WEBHOOK_URL = os.getenv("N8N_VENDOR_ORDER_SHIPMENT_LINK_WEBHOOK_URL", "")
N8N_VENDOR_ORDER_PAYMENT_RELEASED_WEBHOOK_URL = os.getenv("N8N_VENDOR_ORDER_PAYMENT_RELEASED_WEBHOOK_URL", "")
N8N_VENDOR_ORDER_STATUS_CHECKIN_WEBHOOK_URL = os.getenv("N8N_VENDOR_ORDER_STATUS_CHECKIN_WEBHOOK_URL", "")


def _post_webhook(url: str, payload: dict, *, dev_message: str) -> dict:
    """
    Shared POST + response-shaping logic for both n8n webhooks. Returns
    {status: "Sent"|"Simulated"|"Failed", message_id, response_body}.
    """
    if not url:
        print(dev_message)
        return {"status": "Simulated", "message_id": None, "response_body": "n8n not configured (dev mode)"}

    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = N8N_WEBHOOK_SECRET

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        if resp.status_code >= 400:
            return {"status": "Failed", "message_id": None, "response_body": resp.text[:500]}
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass
        return {
            "status": "Sent",
            "message_id": data.get("message_id") if isinstance(data, dict) else None,
            "response_body": resp.text[:500],
        }
    except Exception as e:
        return {"status": "Failed", "message_id": None, "response_body": str(e)}


def trigger_vendor_reorder_email(
    order: dict,
    invoice: dict,
    accept_url: str,
    reject_url: str,
    invoice_pdf_url: str,
) -> dict:
    """
    POST the reorder payload to the n8n webhook that emails the vendor with
    an itemized bill + Accept/Reject buttons.
    """
    # order["id"] is a UUID, invoice/order fields can carry Decimal (NUMERIC
    # columns) and date (expected_delivery is DATE) — none of those survive
    # stdlib json.dumps (which is all httpx's json= param does). Unlike
    # FastAPI's own response path, a manual httpx.post never gets FastAPI's
    # encoder for free, so sanitize explicitly.
    payload = jsonable_encoder({
        "order_id":         order["id"],
        "order_code":       order["order_code"],
        "item_name":        order["item_name"],
        "quantity":         float(order["quantity"]),
        "unit":             order["unit"],
        "vendor_name":      order["vendor_name"],
        "vendor_email":     email_service.vendor_recipient(order["vendor_email"]),
        "expected_delivery": str(order["expected_delivery"]),
        "invoice":          invoice,
        "invoice_pdf_url":  invoice_pdf_url,
        "accept_url":       accept_url,
        "reject_url":       reject_url,
        "trigger_type":     order["trigger_type"],
    })

    dev_message = (
        f"\n[DEV MODE — n8n not configured] Would POST vendor reorder email for "
        f"{order['order_code']} to {order['vendor_email']}\n"
        f"  Accept: {accept_url}\n"
        f"  Reject: {reject_url}\n"
        f"  Invoice PDF: {invoice_pdf_url}\n"
    )
    return _post_webhook(N8N_WEBHOOK_URL, payload, dev_message=dev_message)


def trigger_contract_confirmation_email(
    order: dict,
    invoice: dict,
    invoice_pdf_url: str,
    contract_hash: str,
    execution_hash: str,
) -> dict:
    """
    POST to the n8n webhook that emails the vendor a copy of the now-executed
    smart contract (the finalized bill) once they've accepted a reorder —
    confirming to them that the order is locked in.
    """
    payload = jsonable_encoder({
        "order_id":        order["id"],
        "order_code":      order["order_code"],
        "item_name":       order["item_name"],
        "quantity":        float(order["quantity"]),
        "unit":            order["unit"],
        "vendor_name":     order["vendor_name"],
        "vendor_email":    email_service.vendor_recipient(order["vendor_email"]),
        "invoice":         invoice,
        "invoice_pdf_url": invoice_pdf_url,
        "contract_hash":   contract_hash,
        "execution_hash":  execution_hash,
        "trigger_type":    order["trigger_type"],
    })

    dev_message = (
        f"\n[DEV MODE — n8n not configured] Would POST contract confirmation email for "
        f"{order['order_code']} to {order['vendor_email']}\n"
        f"  Contract hash: {contract_hash}\n"
        f"  Execution hash: {execution_hash}\n"
        f"  Invoice PDF: {invoice_pdf_url}\n"
    )
    return _post_webhook(N8N_CONTRACT_CONFIRMATION_WEBHOOK_URL, payload, dev_message=dev_message)


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — vendor_orders (order -> accept/reject -> contract -> shipment)
#
# Routed through direct SMTP (email_service.py), not n8n — n8n isn't running
# in this deployment. The n8n workflow JSONs under n8n-workflows/ and the
# N8N_VENDOR_ORDER_*_WEBHOOK_URL env vars are left in place; switching back
# just means restoring the _post_webhook(...) call in each function below.
# ─────────────────────────────────────────────────────────────────────────

def trigger_vendor_order_email(
    order: dict,
    items: list,
    accept_url: str,
    reject_url: str,
    expires_at: str,
) -> dict:
    """New order against the vendor's own catalogue (vendor_items) —
    itemized bill + Accept/Reject, no login needed."""
    ok = email_service.send_vendor_order_placed_email(
        order["vendor_email"], order["vendor_name"], order["order_code"],
        order["destination_name"], items, float(order["subtotal"]),
        float(order["total_amount"]), order["currency"], str(expires_at),
        accept_url, reject_url,
    )
    return {"status": "Sent" if ok else "Failed", "message_id": None, "response_body": "direct SMTP"}


def trigger_vendor_order_shipment_link_email(
    order: dict,
    shipment_update_url: str,
) -> dict:
    """Sent right after the vendor accepts — gives them the no-login link
    to report Dispatched / In Transit / Out for Delivery updates."""
    ok = email_service.send_vendor_order_shipment_link_email(
        order["vendor_email"], order["vendor_name"], order["order_code"], shipment_update_url,
    )
    return {"status": "Sent" if ok else "Failed", "message_id": None, "response_body": "direct SMTP"}


def trigger_vendor_order_status_checkin_email(
    order: dict,
    items: list,
    shipment_update_url: str,
) -> dict:
    """Sent ~3x/day while a shipment is in flight (vendor_orders.py's
    check_vendor_status_checkins) — a friendly "what's the status?" nudge
    with a fresh copy of the no-login shipment-update link, reusing the
    same page as the one sent at acceptance."""
    ok = email_service.send_vendor_order_status_checkin_email(
        order["vendor_email"], order["vendor_name"], order["order_code"],
        order["contract_status"], shipment_update_url,
    )
    return {"status": "Sent" if ok else "Failed", "message_id": None, "response_body": "direct SMTP"}


def trigger_vendor_order_payment_released_email(order: dict) -> dict:
    """Sent when the vendor payout is actually made (payments.release_payout
    — after the contract executes and the settlement window elapses), not
    at approval time — so the vendor is only ever told money is on its way
    once it really is. Amount is the vendor's payout (subtotal), in PKR."""
    ok = email_service.send_vendor_order_payment_released_email(
        order["vendor_email"], order["vendor_name"], order["order_code"],
        float(order.get("vendor_payout_amount") or order["subtotal"]), "PKR",
        payout_ref=order.get("payout_ref"),
    )
    return {"status": "Sent" if ok else "Failed", "message_id": None, "response_body": "direct SMTP"}


def trigger_vendor_order_cancelled_email(
    order: dict,
    items: list,
    reason: str,
    cancelled_by: str,
    shipment_started: bool = False,
) -> dict:
    """Sent when an order is cancelled — by the orderer while awaiting the
    vendor's response, or by an admin before arrival — with the reason."""
    ok = email_service.send_vendor_order_cancelled_email(
        order["vendor_email"], order["vendor_name"], order["order_code"], items,
        float(order["total_amount"]), order["currency"], reason, cancelled_by,
        order["orderer_email"], shipment_started=shipment_started,
    )
    return {"status": "Sent" if ok else "Failed", "message_id": None, "response_body": "direct SMTP"}


def trigger_vendor_order_disputed_email(
    order: dict,
    items: list,
    reason: str,
    raised_by: str,
) -> dict:
    """Sent when the orderer disputes a delivery after arrival, with the reason."""
    ok = email_service.send_vendor_order_disputed_email(
        order["vendor_email"], order["vendor_name"], order["order_code"], items,
        float(order["total_amount"]), order["currency"], reason, raised_by,
        order["orderer_email"],
    )
    return {"status": "Sent" if ok else "Failed", "message_id": None, "response_body": "direct SMTP"}
