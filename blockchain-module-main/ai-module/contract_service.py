"""
NEXUS ERP — Smart Contract Service
Simulates Hyperledger Fabric smart contract lifecycle.
Replace the fabric_sdk calls with real SDK in Iteration 2.

Contract lifecycle:
  Created → VendorSigned → OperatorSigned → Executed | Rejected
"""
import hashlib
import json
import uuid
import secrets
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Contract payload builder
# ---------------------------------------------------------------------------

def build_contract_payload(
    order_code: str,
    item_name: str,
    quantity: float,
    unit: str,
    vendor_name: str,
    vendor_email: str,
    unit_price: Optional[float],
    expected_delivery: str,
) -> dict:
    """Build the full smart contract data payload."""
    total = round(quantity * unit_price, 2) if unit_price else None
    return {
        "contract_id":        f"SC-{uuid.uuid4().hex[:8].upper()}",
        "version":            "1.0",
        "network":            "nexus-fabric-channel",
        "chaincode":          "procurement_chaincode",
        "order_code":         order_code,
        "item":               item_name,
        "quantity":           quantity,
        "unit":               unit,
        "vendor":             vendor_name,
        "vendor_email":       vendor_email,
        "unit_price":         unit_price,
        "total_price":        total,
        "expected_delivery":  expected_delivery,
        "terms": {
            "payment_on_delivery": True,
            "quality_check_required": True,
            "partial_delivery_allowed": False,
            "auto_execute_on_delivery": True,
        },
        "created_at":         datetime.utcnow().isoformat() + "Z",
        "signatories":        [],
        "status":             "Pending",
    }


def generate_tx_hash(payload: dict) -> str:
    """Generate a deterministic tx-hash from the contract payload."""
    raw = json.dumps(payload, sort_keys=True) + secrets.token_hex(8)
    return "0x" + hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Fabric SDK stub — replace with real calls in Iteration 2
# ---------------------------------------------------------------------------

def fabric_invoke(function: str, args: list) -> dict:
    """
    Stub for Hyperledger Fabric SDK invoke.
    In Iteration 2, replace with:
        from fabric_sdk_py import ...
    """
    block_number = int(datetime.utcnow().timestamp()) % 100000
    return {
        "success":      True,
        "block_number": block_number,
        "tx_id":        secrets.token_hex(32),
        "timestamp":    datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_smart_contract(
    order_code: str,
    item_name: str,
    quantity: float,
    unit: str,
    vendor_name: str,
    vendor_email: str,
    unit_price: Optional[float],
    expected_delivery: str,
) -> dict:
    """
    Create a new smart contract for a procurement order.
    Returns: { contract_hash, contract_data, block_number }
    """
    payload = build_contract_payload(
        order_code, item_name, quantity, unit,
        vendor_name, vendor_email, unit_price, expected_delivery,
    )
    result = fabric_invoke("createContract", [json.dumps(payload)])
    tx_hash = generate_tx_hash(payload)
    payload["tx_hash"] = tx_hash
    payload["block_number"] = result["block_number"]
    return {
        "contract_hash":  tx_hash,
        "contract_data":  payload,
        "block_number":   result["block_number"],
    }


def sign_contract(
    contract_hash: str,
    signatory: str,
    role: str,          # "vendor" | "operator"
    contract_data: dict,
) -> dict:
    """
    Record a signatory on the contract.
    Returns updated contract_data with new signatory appended.
    """
    sig_entry = {
        "signatory":  signatory,
        "role":       role,
        "signed_at":  datetime.utcnow().isoformat() + "Z",
        "sig_hash":   "0x" + hashlib.sha256(
            (signatory + contract_hash + role).encode()
        ).hexdigest()[:16],
    }
    if "signatories" not in contract_data:
        contract_data["signatories"] = []
    contract_data["signatories"].append(sig_entry)

    # Both parties signed → mark as Signed
    roles_signed = {s["role"] for s in contract_data["signatories"]}
    if {"vendor", "operator"}.issubset(roles_signed):
        contract_data["status"] = "Signed"

    fabric_invoke("signContract", [contract_hash, json.dumps(sig_entry)])
    return contract_data


def execute_contract(contract_hash: str, contract_data: dict) -> dict:
    """
    Execute the contract (called automatically on valid delivery check-in).
    Returns { success, executed_at, execution_hash }
    """
    result = fabric_invoke("executeContract", [contract_hash])
    exec_hash = "0x" + hashlib.sha256(
        (contract_hash + "execute" + result["tx_id"]).encode()
    ).hexdigest()
    contract_data["status"]       = "Executed"
    contract_data["executed_at"]  = datetime.utcnow().isoformat() + "Z"
    contract_data["execution_hash"] = exec_hash
    return {
        "success":        True,
        "executed_at":    contract_data["executed_at"],
        "execution_hash": exec_hash,
        "contract_data":  contract_data,
    }


def reject_contract(
    contract_hash: str,
    contract_data: dict,
    reason: str,
) -> dict:
    """Reject the contract (e.g. damaged delivery)."""
    contract_data["status"]      = "Rejected"
    contract_data["rejected_at"] = datetime.utcnow().isoformat() + "Z"
    contract_data["reject_reason"] = reason
    fabric_invoke("rejectContract", [contract_hash, reason])
    return contract_data


def get_contract_status(contract_data: dict) -> str:
    """Derive human-readable status from contract payload."""
    return contract_data.get("status", "Unknown")
