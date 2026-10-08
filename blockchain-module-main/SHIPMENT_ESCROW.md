# Shipment Escrow — Order → Accept → Contract → Ship → Approve → Execute

Phase 2 of the vendor/procurement/shipment/payment expansion. Covers the
real on-chain `ShipmentEscrow` contract, the order lifecycle it enforces,
the (mocked, Phase 4-real-later) payment lifecycle, and how to switch
between a local Hardhat node and the Sepolia testnet. Builds on
`VENDOR_ONBOARDING.md` (Phase 1: vendor registration/vetting/catalogue)
and reuses — rather than duplicates — the n8n accept/reject pattern from
`N8N_AUTOMATION_WIRING.md`.

"Receiver" always means the orderer who placed the order. There is no
separate receiver field or role — the orderer is the sole person who can
confirm arrival, approve receipt, or raise a dispute. Admins can view
everything and resolve disputes/cancel, but cannot approve on the
orderer's behalf — enforced on-chain, not just in the backend.

## End-to-end flow

```
1. Orderer places an order (approved vendor + vendor_items + destination)
   POST /api/vendor-orders  ->  vendor_orders row, status=PENDING_VENDOR
        │
        ▼
2. n8n emails the vendor (vendor-order-email.workflow.json): itemized
   order + Accept/Reject buttons -> React page /vendor/respond (no login)
        │
   ┌────┴────────────────┬─────────────────────┐
   │ ACCEPT               │ REJECT (+reason)     │ NO RESPONSE (72h default)
   ▼                      ▼                      ▼
 chain.create_contract() Orderer notified       check_vendor_order_expiry()
 -> ShipmentEscrow        status=REJECTED        (scheduler, every 5 min)
 .createContract()                               -> status=EXPIRED, orderer
 status=ACCEPTED,                                   + PMs notified
 contract_status=Preparing
 payment: authorize (mocked)
 n8n emails vendor their
 ship-update link
        │
        ▼
3. SHIPMENT STAGE (contract exists, NOT executed)
   Preparing -> Dispatched -> InTransit -> OutForDelivery
   Vendor (via their link, /vendor/shipment, no login) or staff (Order
   Tracking detail page) post each checkpoint:
     chain.record_checkpoint() -> ShipmentEscrow.recordCheckpoint()
     -> shipment_events row (actor_type, location, note, tx_hash)
        │
        ▼
4. Orderer confirms ARRIVAL (Order Tracking detail page)
     chain.confirm_arrival() -> ShipmentEscrow.confirmArrival()
     (reverts unless destinationHash matches, and caller == the orderer's
     own on-chain address)
        │
   ┌────┴─────────────────┐
   │ APPROVE               │ DISPUTE (reason)
   ▼                       ▼
 chain.approve_receipt()  chain.dispute() -> frozen at Disputed
 -> ShipmentEscrow         Admin resolves: back to Arrived | Cancelled
 .approveReceipt()         | Executed (resolveDispute(), payment
 (Arrived -> Approved ->   cancelled/captured to match)
  Executed, atomically,
  one call)
 payment: capture (mocked)
 n8n emails vendor:
 payment released
 invoice PDF available
```

## The contract — `blockchain-module-main/hardhat/contracts/ShipmentEscrow.sol`

One record per order, keyed by `bytes32 orderId = keccak256(order_code)`.
OpenZeppelin `AccessControl` + `ReentrancyGuard`. State machine:

```
None -> Preparing -> Dispatched -> InTransit -> OutForDelivery -> Arrived
                                                                     │
                                                      ┌──────────────┼──────────────┐
                                                      ▼                              ▼
                                                   Approved -> Executed          Disputed
                                                                                    │
                                                                   ┌────────────────┼────────────────┐
                                                                   ▼                ▼                 ▼
                                                                Arrived         Cancelled          Executed
```

- `createContract` — `LOGISTICS_ROLE` only (the backend's own service
  account). Reverts if the order already exists or `receiver` is zero.
- `recordCheckpoint` — `LOGISTICS_ROLE` only. Only `Dispatched` /
  `InTransit` / `OutForDelivery` are legal targets; only forward moves are
  allowed (`InTransit`/`OutForDelivery` may repeat with a fresh checkpoint,
  per the spec); reverts once the contract has moved past `OutForDelivery`.
- `confirmArrival` — **receiver only** (`msg.sender == contract.receiver`).
  Requires `OutForDelivery` or `InTransit`, and the supplied
  `destinationHash` to match the one stored at creation.
- `approveReceipt` — **receiver only**, requires `Arrived`. Sets
  `Approved` then immediately `Executed` in the same call — there is no
  other function that reaches `Executed`, and no way to approve before
  arrival (both enforced by `require()`, both covered by the Hardhat
  tests).
- `dispute` — **receiver only**, requires `Arrived`. Freezes the contract.
- `resolveDispute` — `ADMIN_ROLE` only, requires `Disputed`; resolution
  must be `Arrived`, `Cancelled` or `Executed`.
- `cancel` — `ADMIN_ROLE` only, blocked once `Arrived`.

Events: `ContractCreated`, `StatusChanged`, `CheckpointRecorded`,
`ArrivalConfirmed`, `ReceiptApproved`, `ContractExecuted`, `Disputed`,
`DisputeResolved`, `Cancelled`.

**Oracle-honesty limitation**: the contract cannot observe a physical
truck. `confirmArrival` is an authenticated attestation by the Receiver;
`recordCheckpoint` is an attestation by whichever account holds
`LOGISTICS_ROLE` (the backend — used identically for both vendor-link
updates and staff-entered ones; the distinguishing actor type/id lives in
the off-chain `shipment_events` row and the on-chain `actorType` byte, not
in a different signer). The chain guarantees *who attested* and that the
*sequence* is internally consistent — never that the event was physically
true. A documented limitation, not a bug; a signed GPS/geofence payload
from the receiver's device would close this gap and is a reasonable
stretch goal, not implemented here.

### Hardhat tests (`hardhat/test/ShipmentEscrow.test.js`) — 31 passing

Happy path through every status; every illegal transition (backward
moves, wrong checkpoint status, checkpoint after `OutForDelivery`);
unauthorized caller on every function (including an admin/logistics
account trying `confirmArrival` — being staff grants nothing here);
approval before arrival (reverts); confirmed there is **no** `execute()`
entrypoint at all (the ABI has no such function — the only path to
`Executed` is `approveReceipt` after `Arrived`); double approval; wrong
`destinationHash`; dispute and all three resolution paths; cancel,
including that it's blocked once `Arrived`.

```bash
cd blockchain-module-main/hardhat
npm install
npx hardhat test
```

## Local ↔ Sepolia — config-only switch

| | Local (default) | Sepolia |
|---|---|---|
| `CHAIN_NETWORK` | `hardhat` or `localhost` | `sepolia` |
| `CHAIN_RPC_URL` | `http://127.0.0.1:8545` (needs `npx hardhat node` running) | A free RPC (Alchemy/Chainstack/public) |
| `CHAIN_SIGNER_PRIVATE_KEY` | One of Hardhat's printed dev keys (10000 test ETH, no real value) | A throwaway key funded only from a Sepolia faucet |
| Deploy | `npx hardhat run scripts/deploy.js --network localhost` | `npx hardhat run scripts/deploy.js --network sepolia` |

`scripts/deploy.js` writes the deployed address + ABI to
`hardhat/deployments/<network>.json`; `shipment_chain_service.py` reads
that file directly (no shared build step between the two halves of the
project) — the backend's own `CHAIN_NETWORK` env var selects which file.
**No paid services, no mainnet, no real-value key anywhere in this
project.**

```bash
# Local, from scratch:
cd blockchain-module-main/hardhat
npm install
npx hardhat node                                    # leave running — a persistent local chain
npx hardhat run scripts/deploy.js --network localhost
# copy the printed address into ai-module/.env's CONTRACT_ADDRESS (or rely
# on deployments/localhost.json, which shipment_chain_service.py reads by
# default), set CHAIN_SIGNER_PRIVATE_KEY to one of the nine private keys
# `npx hardhat node` prints on startup, restart uvicorn.
```

## Dev mode without any blockchain running

Leave `CHAIN_RPC_URL` unset — `shipment_chain_service.py` prints what each
call would have done instead of connecting, exactly like the n8n/email
dev-mode fallbacks elsewhere in this repo. Every Phase 2 HTTP endpoint,
the whole order/shipment/approval lifecycle, and the frontend all work
fully in this mode — the only difference is `contract_status` advances
purely off the backend's own DB writes, with no `tx_hash` on any
`shipment_events` row and `chain_live_state` always `null` on the tracking
detail page.

## Per-user on-chain wallets — why, and how

The orderer needs to be a real, individually-enforced on-chain identity
(so `confirmArrival`/`approveReceipt`/`dispute` are genuinely
receiver-only, not just checked in Python) — but nobody wants to make ERP
users install a wallet. `get_or_create_user_wallet()` generates a
standard Ethereum keypair per user on first need (`eth_account.Account.create()`),
encrypts the private key at rest with Fernet (`WALLET_ENCRYPTION_KEY`),
and stores it in `user_wallets`. The key is only ever decrypted in memory,
momentarily, to sign that one transaction. `_ensure_funded()` auto-tops-up
a near-empty wallet from the backend's own signer balance before each
signed call — on local Hardhat this is free and instant (default accounts
start with 10000 test ETH); on Sepolia the backend's own signer needs to
be faucet-funded first.

**Trust model, stated plainly**: this is custodial — the backend holds
every user's private key. That's an explicit, documented trade-off for a
no-wallet-required UX in an academic FYP context, not something to carry
into a production system without reconsidering it (a non-custodial design
would need the ERP to integrate a real wallet — MetaMask, WalletConnect —
and have the user sign client-side instead).

## Chain tx queue — "pending on-chain confirmation," never a failed action

Every state-changing chain call writes a `chain_tx_queue` row *before*
being attempted (`shipment_chain_service._attempt()`), then is attempted
immediately. If the RPC is unreachable or the node is mid-restart, the
business action (the order status change, the notification) has already
succeeded off-chain — the row just stays `'pending'`. A scheduler job
(`retry_pending_chain_txs`, wired into `reminder_scheduler.py`'s existing
APScheduler, every 2 minutes) retries it, updating the *same* row in place
(never creating a duplicate). A chain hiccup never blocks or fails a user
action.

## Vendor status check-ins — ~3x/day nudge while a shipment is in flight

Once the vendor accepts, `vendor_orders.py` also schedules
`vendor_orders.next_status_checkin_due` (`NOW() + VENDOR_STATUS_CHECKIN_INTERVAL_HOURS`,
default 8h → ~3/day). A scheduler job (`check_vendor_status_checkins`, part
of `_run_vendor_order_jobs`, every 5 min) emails the vendor
(`vendor-order-status-checkin.workflow.json`) a fresh copy of their
no-login shipment-update link (`/vendor/shipment`, the same page sent at
acceptance) whenever an order is `ACCEPTED` and `contract_status` is still
one of `Preparing`/`Dispatched`/`InTransit`/`OutForDelivery`
(`IN_FLIGHT_CONTRACT_STATUSES`), and bumps `next_status_checkin_due`
another interval out. Each check-in also drops a low-priority
`shipment.status_checkin_sent` in-app notification for the orderer (no
`dedupe_key` — unlike most reminder events here, this one is meant to
recur, see `CLAUDE.md`'s gotcha #7).

Whatever the vendor submits through that link (`_do_shipment_update`) goes
through the exact same path a spontaneous update would — it resets
`next_status_checkin_due` another interval out (no point nagging again
five minutes later) and fires the normal `shipment.dispatched` /
`shipment.in_transit` / `shipment.out_for_delivery` notification to the
orderer, which both Order Tracking pages already live-refresh on via SSE.
The check-ins stop the moment arrival is confirmed
(`confirm_arrival_endpoint` clears `next_status_checkin_due` outright; the
job's own `contract_status` filter is the second line of defense).

## Vendor emails on cancel / dispute — always with the reason

Every cancellation or dispute emails the vendor (direct SMTP,
`email_service.py`, via the `n8n_service.trigger_vendor_order_*` wrappers
like the other vendor-order emails), quoting the user's reason
(HTML-escaped), the item list and what happens next:

| Action | Endpoint | Who | Reason | Vendor email |
|---|---|---|---|---|
| Cancel Order (awaiting vendor response) | `POST /api/vendor-orders/{id}/cancel` `{reason}` | orderer / staff | required — 400 without it | "Order cancelled" — Accept/Reject link no longer works, nothing ships |
| Cancel contract (accepted, not yet arrived) | `POST /api/vendor-orders/{id}/cancel-contract` `{reason}` | admin | required | "Order cancelled" — stop any dispatch, arrange return if already shipped |
| Raise Dispute (after arrival) | `POST /api/shipments/{id}/dispute` `{reason}` | orderer | required | "Dispute raised" — contract frozen, payment on hold pending admin review, reply with evidence |

Both cancel paths store the reason in `vendor_orders.cancellation_reason`
(migration `016_vendor_order_cancellation_reason.sql`), shown on the
tracking detail page. Each response includes `vendor_email_status`
(`Sent` / `Failed`). The email is sent after the DB commit, so an SMTP
failure never rolls back the cancellation or dispute. The email names the
orderer (with a mailto link to their email) as the contact for questions.

## Payments — PKR only (`payments.py`, migration `013_add_payment_methods.sql`)

All money is Pakistani Rupees, enforced by `CHECK (currency = 'PKR')` on
`vendor_orders`, `payment_methods` and `payment_transactions`.

| When | What happens to the money | Code |
|---|---|---|
| Order placed | `total_amount = subtotal + platform_fee` (`PLATFORM_FEE_RATE`, default 0.5%). `vendor_payout_amount = subtotal`. Nothing charged. | `place_vendor_order` |
| Vendor accepts | `total_amount` **authorized** (held) on the admin's default payment method, *then* the contract is created with `amount` in paisa and `paymentRef = keccak256(payment_ref)`. No default method -> `Payment Required` + `payment.required` notification; setting a default later auto-authorizes waiting orders. | `payments.authorize_for_order` |
| Orderer approves receipt (only after `Arrived`) | Refused (409) unless funds are held. Contract executes on-chain, hold is **captured**, payout scheduled for `NOW() + PAYOUT_SETTLEMENT_HOURS` (default 24). | `payments.capture_for_order` |
| Payout due | Scheduler (`process_due_payouts`, every 5 min) pays `vendor_payout_amount` to the vendor's IBAN on file and emails the vendor. Admin can "Pay now" from Payments. No IBAN -> payout `Failed`, retryable. | `payments.release_payout` |
| Dispute -> Cancelled, or admin cancels an in-flight contract (`POST /api/vendor-orders/{id}/cancel-contract`) | Hold released, payout `Not Applicable`. | `payments.cancel_for_order` |
| Dispute -> Executed | Same as approval: capture + scheduled payout. | |

**Who moves the money — `PAYMENT_PROVIDER`** (`payment_providers.py`):
`mock` simulates everything. `manual` is the real process with an ordinary
business bank account: when a payout falls due it becomes **Awaiting
Transfer** and appears under "Transfers to make" on the Payments page with
the vendor's account title, bank, full IBAN, amount and a reference
(`NEXUS VO-XXXXXX`), plus a bulk-upload CSV. An admin sends it from the
bank's corporate portal (Raast or IBFT) and records the bank's transaction
ID (`POST /api/payments/orders/{id}/confirm-payout`, duplicate references
rejected). Only then is it Paid and the vendor emailed. `raast_api`
(automated payouts via a licensed Raast Business API provider) is reserved
and refuses to start until implemented against that provider's docs.
`PAYMENT_MAX_ORDER_PKR` (default 10,000,000) caps a single order's total.

Every money movement is logged to `payment_transactions`. The admin
**Payments** page (`/admin/payments`) shows the ledger, summary, payment
methods (bank transfer/IBAN, Raast, JazzCash, Easypaisa — stored in full,
returned masked) and a plain explanation of the flow. The processor itself
(`payment_mock_service.py`) is still simulated — a real PKR gateway slots
in behind the same four functions.

## Invoice — ReportLab PDF reused unchanged

`invoice_service.py` (non-negotiable, call-don't-edit) is hardcoded to a
single line item, because `procurement_orders` only ever has one.
`vendor_orders` supports multiple items per order, so
`vendor_orders._invoice_data()` builds the *same output shape*
(`generate_invoice_data()` would produce) from all of an order's line
items — then calls `invoice_service.generate_invoice_pdf()`, the actual
ReportLab renderer, **completely unmodified**. Only the data-shaping step
is new, because the input genuinely differs in shape; the rendering logic
itself is reused exactly as-is.

## Known limitations

- Custodial per-user wallets (see above) — a deliberate FYP-scope trade-off.
- Payments are mocked (Phase 4 swaps in real Stripe behind the same interface).
- No GPS/geofence attestation for arrival — a documented stretch goal, not implemented.
- `chain_tx_queue` retry gives up after 10 attempts per row (configurable in `shipment_chain_service.retry_pending_chain_txs`).
