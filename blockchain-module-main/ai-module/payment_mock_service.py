"""
NEXUS ERP — Payment Service (Phase 2: mocked; Phase 4: real Stripe)
Per the agreed Phase 2 scope, this is a mock — it simulates the
authorize/capture/cancel lifecycle (status + a fake payment_ref) without
calling any real payment processor, so vendor_orders.py can be written
against the final interface now and swapped to real Stripe calls later
with no caller-side changes.

Lifecycle mirrors what Phase 4 will do for real:
  authorize_order_payment  -- called on vendor acceptance (funds "held")
  capture_order_payment    -- called once the contract executes
  cancel_order_payment     -- called on reject/expiry/cancel/dispute-cancel
"""
import secrets


def authorize_order_payment(order_code: str, amount: float, currency: str) -> dict:
    """Mock: always succeeds. Real Stripe version creates a PaymentIntent
    with capture_method=manual using the org's default saved method."""
    ref = "mock_pi_" + secrets.token_hex(12)
    print(f"[MOCK PAYMENT] Authorized {currency} {amount:,.2f} for {order_code} -> {ref}")
    return {"status": "Authorized", "payment_ref": ref}


def capture_order_payment(order_code: str, payment_ref: str) -> dict:
    print(f"[MOCK PAYMENT] Captured {order_code} ({payment_ref})")
    return {"status": "Captured", "payment_ref": payment_ref}


def cancel_order_payment(order_code: str, payment_ref: str) -> dict:
    print(f"[MOCK PAYMENT] Cancelled/released hold for {order_code} ({payment_ref})")
    return {"status": "Cancelled", "payment_ref": payment_ref}
