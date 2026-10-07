"""
NEXUS ERP — Payment providers (PKR only)
Selected with PAYMENT_PROVIDER. payments.py only ever talks to
get_provider(), so switching provider is a config change.

  mock    — simulated: every step succeeds instantly, vendor payouts are
            "paid" automatically. For local dev and demos only.
  manual  — the real process with an ordinary business bank account,
            no gateway contract needed:
              authorize -> funds are reserved (earmarked) against the
                           organisation's default account in the ledger
              capture   -> the reservation is committed once the contract
                           executes on-chain
              payout    -> becomes 'Awaiting Transfer'. An admin sends the
                           money from the bank's corporate portal (Raast
                           or IBFT, single or bulk-file upload) and records
                           the bank's transaction ID in NEXUS. Only then is
                           the payout marked Paid and the vendor emailed.
  raast_api — automated payouts through a licensed Raast Business API
            provider (1LINK, PayFast, Finja, NayaPay or SadaPay Business).
            Not implemented yet: each provider's request format and
            signing scheme come from its merchant documentation, which is
            issued on signing up. Selecting it fails loudly at startup
            rather than pretending to pay anyone.

Each provider returns plain dicts:
  authorize -> {"status": "Authorized" | "Payment Required" | "Failed", "payment_ref", "error"}
  capture   -> {"status": "Captured" | "Failed", "payment_ref", "error"}
  cancel    -> {"status": "Cancelled", "payment_ref", "error"}
  payout    -> {"status": "Paid" | "Awaiting Transfer" | "Failed", "payout_ref", "error"}
"""
import os
import secrets
from typing import Optional

import payment_mock_service as mock

CURRENCY = mock.CURRENCY
require_pkr = mock.require_pkr


class MockProvider:
    name = "mock"
    label = "Simulated (no real money moves)"
    automatic_payouts = True

    def authorize(self, order_code, amount, currency, method):
        return mock.authorize_order_payment(order_code, amount, currency, method)

    def capture(self, order_code, payment_ref, amount, currency):
        return mock.capture_order_payment(order_code, payment_ref, amount, currency)

    def cancel(self, order_code, payment_ref):
        return mock.cancel_order_payment(order_code, payment_ref)

    def payout(self, order_code, amount, currency, vendor):
        return mock.payout_to_vendor(order_code, amount, currency, vendor)


class ManualBankTransferProvider:
    name = "manual"
    label = "Bank transfer (Raast / IBFT) recorded by an admin"
    automatic_payouts = False

    def authorize(self, order_code, amount, currency, method):
        require_pkr(currency)
        if not method:
            return {"status": "Payment Required", "payment_ref": None, "error": "No default payment method configured"}
        ref = f"RSV-{order_code}-{secrets.token_hex(3).upper()}"
        return {"status": "Authorized", "payment_ref": ref, "error": None}

    def capture(self, order_code, payment_ref, amount, currency):
        require_pkr(currency)
        return {"status": "Captured", "payment_ref": payment_ref, "error": None}

    def cancel(self, order_code, payment_ref):
        return {"status": "Cancelled", "payment_ref": payment_ref, "error": None}

    def payout(self, order_code, amount, currency, vendor):
        require_pkr(currency)
        if not (vendor.get("bank_iban") or "").strip():
            return {"status": "Failed", "payout_ref": None, "error": "Vendor has no bank IBAN on file"}
        return {"status": "Awaiting Transfer", "payout_ref": None, "error": None}


_PROVIDERS = {"mock": MockProvider, "manual": ManualBankTransferProvider}
_instance = None


def get_provider():
    global _instance
    if _instance is None:
        name = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
        if name == "raast_api":
            raise RuntimeError(
                "PAYMENT_PROVIDER=raast_api is not implemented yet — it needs the merchant API docs and "
                "credentials from your chosen Raast Business API provider. Use 'manual' until then."
            )
        if name not in _PROVIDERS:
            raise RuntimeError(f"Unknown PAYMENT_PROVIDER '{name}' (expected one of: {', '.join(_PROVIDERS)})")
        _instance = _PROVIDERS[name]()
    return _instance
