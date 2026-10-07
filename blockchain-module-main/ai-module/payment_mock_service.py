"""
NEXUS ERP — Payment Processor (mocked; a real PKR gateway later)
Per the agreed scope, this is a mock — it simulates the authorize/capture/
cancel/payout lifecycle (status + a fake reference) without calling any
real payment processor, so payments.py (the orchestration + ledger layer)
can be written against the final interface now and swapped to a real
Pakistani gateway (e.g. a bank's IBFT/Raast API, JazzCash/Easypaisa
merchant APIs) later with no caller-side changes.

PKR only — every function rejects any other currency outright rather than
silently treating the number as rupees.

Lifecycle:
  authorize_order_payment  -- vendor accepts: hold total_amount on the org's
                              default payment method (escrow)
  capture_order_payment    -- receipt approved + contract executed: capture
                              the held funds
  cancel_order_payment     -- reject/cancel/dispute-cancel: release the hold
  payout_to_vendor         -- payout due: transfer vendor_payout_amount to
                              the vendor's IBAN on file
"""
import secrets
from typing import Optional

CURRENCY = "PKR"


class UnsupportedCurrencyError(ValueError):
    pass


def require_pkr(currency: Optional[str]):
    if (currency or "").upper() != CURRENCY:
        raise UnsupportedCurrencyError(f"Only {CURRENCY} is supported (got {currency!r})")


def authorize_order_payment(order_code: str, amount: float, currency: str, method: Optional[dict]) -> dict:
    """Mock: succeeds whenever a payment method is supplied. With no method
    configured, nothing can be held — the caller marks the order
    'Payment Required' and asks an admin to add one."""
    require_pkr(currency)
    if not method:
        print(f"[MOCK PAYMENT] No payment method configured — cannot authorize {order_code}")
        return {"status": "Payment Required", "payment_ref": None, "error": "No default payment method configured"}
    ref = "mock_auth_" + secrets.token_hex(10)
    print(f"[MOCK PAYMENT] Authorized PKR {amount:,.2f} for {order_code} on '{method.get('label')}' -> {ref}")
    return {"status": "Authorized", "payment_ref": ref, "error": None}


def capture_order_payment(order_code: str, payment_ref: str, amount: float, currency: str) -> dict:
    require_pkr(currency)
    print(f"[MOCK PAYMENT] Captured PKR {amount:,.2f} for {order_code} ({payment_ref})")
    return {"status": "Captured", "payment_ref": payment_ref, "error": None}


def cancel_order_payment(order_code: str, payment_ref: Optional[str]) -> dict:
    print(f"[MOCK PAYMENT] Cancelled/released hold for {order_code} ({payment_ref})")
    return {"status": "Cancelled", "payment_ref": payment_ref, "error": None}


def payout_to_vendor(order_code: str, amount: float, currency: str, vendor: dict) -> dict:
    """Mock IBFT/Raast transfer to the vendor's IBAN. Fails (rather than
    pretending) when the vendor has no IBAN on file."""
    require_pkr(currency)
    iban = (vendor.get("bank_iban") or "").strip()
    if not iban:
        return {"status": "Failed", "payout_ref": None, "error": "Vendor has no bank IBAN on file"}
    ref = "mock_payout_" + secrets.token_hex(10)
    print(f"[MOCK PAYMENT] Paid out PKR {amount:,.2f} for {order_code} to {vendor.get('name')} "
          f"(IBAN ****{iban[-4:]}) -> {ref}")
    return {"status": "Paid", "payout_ref": ref, "error": None}
