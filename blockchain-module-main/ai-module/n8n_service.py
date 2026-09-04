"""
NEXUS ERP — n8n Automation Bridge
Fires the "vendor reorder email" n8n workflow described in
N8N_AUTOMATION_WIRING.md. Does not build the invoice or the smart contract
itself — those come from invoice_service.py / contract_service.py unchanged;
this module only shapes the webhook payload and posts it.

Dev mode (N8N_WEBHOOK_URL unset): prints the payload instead of posting,
matching the same graceful-fallback pattern email_service.py already uses
for SMTP.
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "")


def trigger_vendor_reorder_email(
    order: dict,
    invoice: dict,
    accept_url: str,
    reject_url: str,
    invoice_pdf_url: str,
) -> dict:
    """
    POST the reorder payload to the n8n webhook that emails the vendor with
    an itemized bill + Accept/Reject buttons. Returns
    {status: "Sent"|"Simulated"|"Failed", message_id, response_body}.
    """
    payload = {
        "order_id":         order["id"],
        "order_code":       order["order_code"],
        "item_name":        order["item_name"],
        "quantity":         float(order["quantity"]),
        "unit":             order["unit"],
        "vendor_name":      order["vendor_name"],
        "vendor_email":     order["vendor_email"],
        "expected_delivery": str(order["expected_delivery"]),
        "invoice":          invoice,
        "invoice_pdf_url":  invoice_pdf_url,
        "accept_url":       accept_url,
        "reject_url":       reject_url,
        "trigger_type":     order["trigger_type"],
    }

    if not N8N_WEBHOOK_URL:
        print(f"\n[DEV MODE — n8n not configured] Would POST vendor reorder email for "
              f"{order['order_code']} to {order['vendor_email']}")
        print(f"  Accept: {accept_url}")
        print(f"  Reject: {reject_url}")
        print(f"  Invoice PDF: {invoice_pdf_url}\n")
        return {"status": "Simulated", "message_id": None, "response_body": "n8n not configured (dev mode)"}

    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = N8N_WEBHOOK_SECRET

    try:
        resp = httpx.post(N8N_WEBHOOK_URL, json=payload, headers=headers, timeout=15.0)
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
