"""
NEXUS ERP — Shipment Chain Service (Phase 2)
web3.py bridge to the real on-chain ShipmentEscrow contract
(blockchain-module-main/hardhat/contracts/ShipmentEscrow.sol). Separate
from contract_service.py (the pure-Python Hyperledger Fabric simulation
used by the original auto-reorder flow) — this talks to an actual EVM
chain (local Hardhat node by default, Sepolia testnet via env vars).

Design:
  - Dev mode (CHAIN_RPC_URL unset, or the node unreachable): every function
    returns {"confirmed": False, "simulated": True, ...} and prints instead
    of raising — same graceful-fallback philosophy as n8n_service.py /
    email_service.py. The rest of Phase 2 (DB state, HTTP endpoints,
    frontend) works fully without any blockchain infra running.
  - Every state-changing call is written to chain_tx_queue *before* being
    attempted (see 010_add_vendor_orders.sql) — a crash mid-call loses
    nothing, and a revert/RPC failure never raises into the caller: the
    business action it's part of already succeeded off-chain, and the row
    stays 'pending' for retry_pending_chain_txs() (wired into
    reminder_scheduler.py's existing APScheduler) to pick up later.
  - The on-chain "Receiver" is a real per-user address — see
    get_or_create_user_wallet(). confirmArrival/approveReceipt/dispute are
    signed with that specific user's own backend-custodied key, so the
    contract's `require(receiver == msg.sender)` is genuine on-chain
    enforcement, not just an off-chain check. createContract /
    recordCheckpoint / resolveDispute / cancel are signed by the backend's
    own LOGISTICS_ROLE / ADMIN_ROLE service account (CHAIN_SIGNER_PRIVATE_KEY).

Oracle-honesty limitation (see SHIPMENT_ESCROW.md): the chain cannot
observe a physical truck. It only guarantees who *attested* to an event
on-chain and that the sequence is internally consistent — not that the
event is physically true.
"""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()

CHAIN_NETWORK = os.getenv("CHAIN_NETWORK", "hardhat")          # hardhat | localhost | sepolia
CHAIN_RPC_URL = os.getenv("CHAIN_RPC_URL", "")                  # e.g. http://127.0.0.1:8545
CHAIN_SIGNER_PRIVATE_KEY = os.getenv("CHAIN_SIGNER_PRIVATE_KEY", "")
CONTRACT_ADDRESS_OVERRIDE = os.getenv("CONTRACT_ADDRESS", "")
WALLET_ENCRYPTION_KEY = os.getenv("WALLET_ENCRYPTION_KEY", "")
WALLET_FUND_AMOUNT_ETH = float(os.getenv("WALLET_FUND_AMOUNT_ETH", "0.05"))
WALLET_FUND_THRESHOLD_ETH = float(os.getenv("WALLET_FUND_THRESHOLD_ETH", "0.01"))

_DEPLOYMENTS_DIR = Path(__file__).parent.parent / "hardhat" / "deployments"

# ---------------------------------------------------------------------------
# Status / actor-type enums — must mirror ShipmentEscrow.sol exactly.
# ---------------------------------------------------------------------------
STATUS_TO_INT = {
    "None": 0, "Preparing": 1, "Dispatched": 2, "InTransit": 3, "OutForDelivery": 4,
    "Arrived": 5, "Approved": 6, "Executed": 7, "Disputed": 8, "Cancelled": 9,
}
INT_TO_STATUS = {v: k for k, v in STATUS_TO_INT.items()}

ACTOR_TYPE_TO_INT = {"vendor_link": 0, "staff": 1, "receiver": 2, "system": 3}


def order_id_hash(order_code: str) -> str:
    """keccak256(order_code) — the on-chain mapping key for this order."""
    from eth_utils import keccak
    return "0x" + keccak(text=order_code).hex()


def content_hash(value) -> str:
    """keccak256 of any value's string form (destination, vendor id, reason,
    etc.) — callers sometimes pass a DB row's UUID object directly rather
    than pre-stringifying it, so coerce defensively rather than relying on
    every call site remembering to str() first."""
    from eth_utils import keccak
    return "0x" + keccak(text=str(value) if value is not None else "").hex()


# ---------------------------------------------------------------------------
# web3 connection + contract — lazy, dev-mode tolerant
# ---------------------------------------------------------------------------
_w3 = None
_contract = None
_backend_account = None
_init_attempted = False


def _load_deployment() -> Optional[dict]:
    path = _DEPLOYMENTS_DIR / f"{CHAIN_NETWORK}.json"
    if not path.is_file():
        return None
    with open(path) as f:
        return json.load(f)


_INIT_RETRY_COOLDOWN_S = 30
_last_init_attempt = 0.0


def _init():
    """Connect lazily, self-healing: if CHAIN_RPC_URL is set but the first
    attempt fails (node not up yet, restarted, etc.), every call here
    retries — bounded by a cooldown so a sustained outage doesn't block
    every single request on a fresh 10s connection timeout. Once connected
    successfully, short-circuits immediately forever (no further attempts
    needed). Never raises — leaves _w3/_contract as None on any failure,
    which every public function below checks for."""
    global _w3, _contract, _backend_account, _init_attempted, _last_init_attempt
    if _contract is not None:
        return  # already connected

    if not CHAIN_RPC_URL:
        if not _init_attempted:
            print("[DEV MODE — shipment_chain_service] CHAIN_RPC_URL not set; chain calls will be simulated.")
            _init_attempted = True
        return

    now = time.time()
    if _init_attempted and (now - _last_init_attempt) < _INIT_RETRY_COOLDOWN_S:
        return  # still cooling down since the last failed attempt
    _init_attempted = True
    _last_init_attempt = now

    try:
        from web3 import Web3
        from eth_account import Account

        w3 = Web3(Web3.HTTPProvider(CHAIN_RPC_URL, request_kwargs={"timeout": 10}))
        if not w3.is_connected():
            print(f"[WARN] shipment_chain_service: could not connect to {CHAIN_RPC_URL}; chain calls will be simulated.")
            return

        deployment = _load_deployment()
        address = CONTRACT_ADDRESS_OVERRIDE or (deployment["address"] if deployment else "")
        if not address:
            print(f"[WARN] shipment_chain_service: no contract address for network '{CHAIN_NETWORK}' "
                  f"(deploy with hardhat/scripts/deploy.js first); chain calls will be simulated.")
            return
        abi = deployment["abi"] if deployment else None
        if abi is None:
            print("[WARN] shipment_chain_service: no ABI available; chain calls will be simulated.")
            return

        if not CHAIN_SIGNER_PRIVATE_KEY:
            print("[WARN] shipment_chain_service: CHAIN_SIGNER_PRIVATE_KEY not set; chain calls will be simulated.")
            return

        _w3 = w3
        _contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        _backend_account = Account.from_key(CHAIN_SIGNER_PRIVATE_KEY)
        print(f"[OK] shipment_chain_service connected to {CHAIN_NETWORK} at {address}, "
              f"backend signer {_backend_account.address}")
    except Exception as e:
        print(f"[WARN] shipment_chain_service init failed: {e}; chain calls will be simulated.")


def is_configured() -> bool:
    _init()
    return _contract is not None


def chain_status() -> dict:
    """For the admin 'Chain status' indicator and check_chain_health().
    `rpc_configured` (CHAIN_RPC_URL set at all) is deliberately distinct
    from `configured` (a contract is actually loaded and ready) — a
    misconfigured/down node from the very first call has rpc_configured=True,
    configured=False, which is the real "unreachable, should alert admins"
    signal. Dev mode (CHAIN_RPC_URL unset entirely) has rpc_configured=False,
    which is an intentional choice, not an outage."""
    _init()
    connected = False
    if _w3 is not None:
        try:
            connected = _w3.is_connected()
        except Exception:
            connected = False
    return {
        "rpc_configured": bool(CHAIN_RPC_URL),
        "configured": _contract is not None,
        "connected": connected,
        "network": CHAIN_NETWORK,
        "contract_address": _contract.address if _contract is not None else None,
    }


# ---------------------------------------------------------------------------
# Fernet encryption for per-user wallet keys
# ---------------------------------------------------------------------------
_fernet_instance = None


def _fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    from cryptography.fernet import Fernet
    key = WALLET_ENCRYPTION_KEY
    if not key:
        key = Fernet.generate_key().decode()
        print("[WARN] WALLET_ENCRYPTION_KEY not set — generated an in-memory key for this process only. "
              "User wallets created now will be unreadable after a restart. Set WALLET_ENCRYPTION_KEY in .env "
              "for any persistent deployment.")
    _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet_instance


def get_or_create_user_wallet(db: Session, user_id: str) -> str:
    """Returns the user's backend-custodied address, creating one if needed."""
    row = db.execute(
        text("SELECT address FROM user_wallets WHERE user_id = :id"), {"id": user_id}
    ).mappings().first()
    if row:
        return row["address"]

    from eth_account import Account
    acct = Account.create()
    encrypted = _fernet().encrypt(acct.key.hex().encode()).decode()
    db.execute(
        text("""
            INSERT INTO user_wallets (user_id, address, encrypted_private_key)
            VALUES (:uid, :addr, :key)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {"uid": user_id, "addr": acct.address, "key": encrypted},
    )
    db.commit()
    return acct.address


def _get_user_account(db: Session, user_id: str):
    row = db.execute(
        text("SELECT encrypted_private_key FROM user_wallets WHERE user_id = :id"), {"id": user_id}
    ).mappings().first()
    if not row:
        raise RuntimeError(f"No on-chain wallet for user {user_id} yet — call get_or_create_user_wallet first")
    from eth_account import Account
    raw_key = _fernet().decrypt(row["encrypted_private_key"].encode()).decode()
    return Account.from_key(raw_key)


def _ensure_funded(address: str):
    """Top up a near-empty wallet from the backend signer's own balance so
    its transactions don't fail for lack of gas. No-op if already funded
    above the threshold, or if the backend signer itself has no balance
    (e.g. a Sepolia deploy key that was never funded — logged, not raised)."""
    if _w3 is None:
        return
    threshold = _w3.to_wei(WALLET_FUND_THRESHOLD_ETH, "ether")
    balance = _w3.eth.get_balance(address)
    if balance >= threshold:
        return
    try:
        amount = _w3.to_wei(WALLET_FUND_AMOUNT_ETH, "ether")
        tx = {
            "from": _backend_account.address,
            "to": address,
            "value": amount,
            "nonce": _w3.eth.get_transaction_count(_backend_account.address),
            "gas": 21000,
            "gasPrice": _w3.eth.gas_price,
            "chainId": _w3.eth.chain_id,
        }
        signed = _backend_account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = _w3.eth.send_raw_transaction(raw)
        _w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    except Exception as e:
        print(f"[WARN] shipment_chain_service: could not fund user wallet {address}: {e}")


# ---------------------------------------------------------------------------
# Transaction queue — write-then-attempt, retry-safe
# ---------------------------------------------------------------------------

def _enqueue(db: Session, order_id: str, action: str, payload: dict) -> str:
    queue_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO chain_tx_queue (id, order_id, action, payload, status, attempts)
            VALUES (:id, :oid, :action, CAST(:payload AS jsonb), 'pending', 1)
        """),
        {"id": queue_id, "oid": order_id, "action": action, "payload": json.dumps(jsonable_encoder(payload))},
    )
    db.commit()
    return queue_id


def _mark_confirmed(db: Session, queue_id: str, tx_hash: str, block_number: int):
    db.execute(
        text("""
            UPDATE chain_tx_queue SET status='confirmed', tx_hash=:h, block_number=:b, updated_at=NOW()
            WHERE id=:id
        """),
        {"h": tx_hash, "b": block_number, "id": queue_id},
    )
    db.commit()


def _mark_failed_pending(db: Session, queue_id: str, error: str):
    db.execute(
        text("""
            UPDATE chain_tx_queue
            SET status='pending', attempts = attempts + 1, last_error=:e, updated_at=NOW()
            WHERE id=:id
        """),
        {"e": str(error)[:500], "id": queue_id},
    )
    db.commit()


def _send_and_wait(fn_call, account) -> tuple:
    """Simulate via .call() first (surfaces the exact revert reason), then
    send+sign+wait for real. Returns (tx_hash_hex, block_number)."""
    fn_call.call({"from": account.address})  # raises ContractLogicError with the require() message on revert
    tx = fn_call.build_transaction({
        "from": account.address,
        "nonce": _w3.eth.get_transaction_count(account.address),
        "gas": 500000,
        "gasPrice": _w3.eth.gas_price,
        "chainId": _w3.eth.chain_id,
    })
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = _w3.eth.send_raw_transaction(raw)
    receipt = _w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    if receipt.status != 1:
        raise RuntimeError("transaction reverted on-chain")
    return tx_hash.hex(), receipt.blockNumber


def _attempt(db: Session, order_id: str, action: str, payload: dict, call_fn, queue_id: Optional[str] = None) -> dict:
    """call_fn() -> (tx_hash, block_number) or raises. Never propagates —
    always returns a result dict; failures leave the queue row 'pending'.

    `queue_id` distinguishes a first attempt (None — a fresh row is
    enqueued) from a retry of an existing row (passed in by
    retry_pending_chain_txs) — a retry always updates that same row rather
    than enqueueing a new one, so a row that eventually succeeds doesn't
    leave a stale duplicate 'pending' row behind it."""
    _init()
    if _contract is None:
        print(f"[DEV MODE — shipment_chain_service] Would call {action} for order {order_id}: {payload}")
        return {"confirmed": False, "simulated": True, "tx_hash": None, "block_number": None, "error": None}

    is_retry = queue_id is not None
    if not is_retry:
        queue_id = _enqueue(db, order_id, action, payload)
    try:
        tx_hash, block_number = call_fn()
        _mark_confirmed(db, queue_id, tx_hash, block_number)
        return {"confirmed": True, "simulated": False, "tx_hash": tx_hash, "block_number": block_number, "error": None}
    except Exception as e:
        _mark_failed_pending(db, queue_id, str(e))
        print(f"[WARN] shipment_chain_service: {action} for order {order_id} failed"
              f"{' (retry)' if is_retry else ', queued for retry'}: {e}")
        return {"confirmed": False, "simulated": False, "tx_hash": None, "block_number": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Public API — one function per contract entrypoint
# ---------------------------------------------------------------------------

def create_contract(
    db: Session, order_id: str, order_code: str, receiver_address: str,
    vendor_id: str, destination: str, order_terms_summary: str, amount: int,
    _queue_id: Optional[str] = None,
) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {
        "order_code": order_code, "receiver_address": receiver_address, "vendor_id": vendor_id,
        "destination": destination, "order_terms_summary": order_terms_summary, "amount": amount,
    }

    def call():
        return _send_and_wait(
            _contract.functions.createContract(
                oid_hash, _w3.to_checksum_address(receiver_address), content_hash(vendor_id),
                content_hash(destination), content_hash(order_terms_summary), int(amount),
                content_hash(""),  # paymentRef — set once Phase 4 payments land
            ),
            _backend_account,
        )

    result = _attempt(db, order_id, "create_contract", payload, call, queue_id=_queue_id)
    result["chain_order_id"] = oid_hash
    result["destination_hash"] = content_hash(destination)
    result["order_hash"] = content_hash(order_terms_summary)
    return result


def record_checkpoint(
    db: Session, order_id: str, order_code: str, new_status: str,
    location: str, note: str, actor_type: str,
    _queue_id: Optional[str] = None,
) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {"order_code": order_code, "new_status": new_status, "location": location, "note": note, "actor_type": actor_type}

    def call():
        return _send_and_wait(
            _contract.functions.recordCheckpoint(
                oid_hash, STATUS_TO_INT[new_status], location or "", content_hash(note),
                ACTOR_TYPE_TO_INT.get(actor_type, 3),
            ),
            _backend_account,
        )

    return _attempt(db, order_id, "record_checkpoint", payload, call, queue_id=_queue_id)


def confirm_arrival(
    db: Session, order_id: str, order_code: str, destination: str, user_id: str,
    _queue_id: Optional[str] = None,
) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {"order_code": order_code, "destination": destination, "user_id": user_id}

    def call():
        account = _get_user_account(db, user_id)
        _ensure_funded(account.address)
        return _send_and_wait(
            _contract.functions.confirmArrival(oid_hash, content_hash(destination)), account
        )

    return _attempt(db, order_id, "confirm_arrival", payload, call, queue_id=_queue_id)


def approve_receipt(
    db: Session, order_id: str, order_code: str, user_id: str, _queue_id: Optional[str] = None,
) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {"order_code": order_code, "user_id": user_id}

    def call():
        account = _get_user_account(db, user_id)
        _ensure_funded(account.address)
        return _send_and_wait(_contract.functions.approveReceipt(oid_hash), account)

    return _attempt(db, order_id, "approve_receipt", payload, call, queue_id=_queue_id)


def dispute(
    db: Session, order_id: str, order_code: str, reason: str, user_id: str, _queue_id: Optional[str] = None,
) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {"order_code": order_code, "reason": reason, "user_id": user_id}

    def call():
        account = _get_user_account(db, user_id)
        _ensure_funded(account.address)
        return _send_and_wait(_contract.functions.dispute(oid_hash, content_hash(reason)), account)

    return _attempt(db, order_id, "dispute", payload, call, queue_id=_queue_id)


def resolve_dispute(
    db: Session, order_id: str, order_code: str, resolution: str, _queue_id: Optional[str] = None,
) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {"order_code": order_code, "resolution": resolution}

    def call():
        return _send_and_wait(
            _contract.functions.resolveDispute(oid_hash, STATUS_TO_INT[resolution]), _backend_account
        )

    return _attempt(db, order_id, "resolve_dispute", payload, call, queue_id=_queue_id)


def cancel(db: Session, order_id: str, order_code: str, _queue_id: Optional[str] = None) -> dict:
    oid_hash = order_id_hash(order_code)
    payload = {"order_code": order_code}

    def call():
        return _send_and_wait(_contract.functions.cancel(oid_hash), _backend_account)

    return _attempt(db, order_id, "cancel", payload, call, queue_id=_queue_id)


def get_state(order_code: str) -> Optional[dict]:
    """Read-only — the chain is the source of truth; call this to reconcile."""
    _init()
    if _contract is None:
        return None
    oid_hash = order_id_hash(order_code)
    try:
        if not _contract.functions.contractExists(oid_hash).call():
            return None
        c = _contract.functions.getContract(oid_hash).call()
        return {
            "receiver": c[0], "vendor_ref": c[1].hex(), "destination_hash": c[2].hex(),
            "order_hash": c[3].hex(), "amount": c[4], "payment_ref": c[5].hex(),
            "status": INT_TO_STATUS.get(c[6], "Unknown"), "created_at": c[7], "updated_at": c[8],
            "checkpoint_count": c[9],
        }
    except Exception as e:
        print(f"[WARN] shipment_chain_service.get_state failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Retry job — wired into reminder_scheduler.py's existing APScheduler
# ---------------------------------------------------------------------------

_ACTION_DISPATCH = {
    "create_contract": lambda db, p, qid: create_contract(
        db, p["_order_id"], p["order_code"], p["receiver_address"], p["vendor_id"],
        p["destination"], p["order_terms_summary"], p["amount"], _queue_id=qid,
    ),
    "record_checkpoint": lambda db, p, qid: record_checkpoint(
        db, p["_order_id"], p["order_code"], p["new_status"], p["location"], p["note"], p["actor_type"], _queue_id=qid,
    ),
    "confirm_arrival": lambda db, p, qid: confirm_arrival(db, p["_order_id"], p["order_code"], p["destination"], p["user_id"], _queue_id=qid),
    "approve_receipt": lambda db, p, qid: approve_receipt(db, p["_order_id"], p["order_code"], p["user_id"], _queue_id=qid),
    "dispute": lambda db, p, qid: dispute(db, p["_order_id"], p["order_code"], p["reason"], p["user_id"], _queue_id=qid),
    "resolve_dispute": lambda db, p, qid: resolve_dispute(db, p["_order_id"], p["order_code"], p["resolution"], _queue_id=qid),
    "cancel": lambda db, p, qid: cancel(db, p["_order_id"], p["order_code"], _queue_id=qid),
}


def retry_pending_chain_txs(db: Session, max_rows: int = 20) -> int:
    """Re-attempt rows stuck 'pending' (RPC hiccup, node restart, etc) —
    each retry updates the *same* queue row in place (via _queue_id), so a
    row that eventually succeeds doesn't leave a stale duplicate behind.
    Returns how many were retried."""
    rows = db.execute(
        text("""
            SELECT id, order_id, action, payload FROM chain_tx_queue
            WHERE status = 'pending' AND attempts < 10
            ORDER BY created_at ASC LIMIT :n
        """),
        {"n": max_rows},
    ).mappings().all()

    retried = 0
    for row in rows:
        action = row["action"]
        fn = _ACTION_DISPATCH.get(action)
        if not fn:
            continue
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        payload["_order_id"] = str(row["order_id"])
        try:
            fn(db, payload, str(row["id"]))
            retried += 1
        except Exception as e:
            print(f"[WARN] retry_pending_chain_txs: {action} retry raised: {e}")
    return retried
