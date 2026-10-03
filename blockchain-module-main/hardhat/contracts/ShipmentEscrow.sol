// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title ShipmentEscrow
/// @notice NEXUS ERP — on-chain shipment/approval state machine for vendor
/// orders placed from the approved vendor catalogue (Phase 2). Separate from
/// and does not replace `contract_service.py`'s simulated Hyperledger Fabric
/// contract used by the original low-stock auto-reorder flow — this is the
/// new, real-chain contract for the order -> accept -> ship -> approve ->
/// execute flow described in VENDOR_ONBOARDING.md / SHIPMENT_ESCROW.md.
///
/// One record per order, keyed by a bytes32 orderId (keccak256 of the
/// order's human-readable code). The contract enforces the state machine —
/// it is the source of truth for status, not the backend database (which
/// only mirrors/indexes it for fast queries).
///
/// Oracle-honesty limitation: a smart contract cannot observe a physical
/// truck. `confirmArrival` is an authenticated attestation by the Receiver
/// (the orderer, via their own backend-custodied signing key — see
/// shipment_chain_service.py); `recordCheckpoint` is an attestation by
/// whichever account holds LOGISTICS_ROLE (the backend's service account,
/// used for both vendor-shipment-link updates and staff-entered updates —
/// the distinguishing actor type/id is carried in the emitted event, not by
/// a different signer). This contract cannot verify either claim against
/// physical reality; it only guarantees who *said* it happened, and that
/// the sequence of events is internally consistent.
contract ShipmentEscrow is AccessControl, ReentrancyGuard {
    bytes32 public constant LOGISTICS_ROLE = keccak256("LOGISTICS_ROLE");
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");

    enum Status {
        None,           // 0 - no contract created yet
        Preparing,      // 1
        Dispatched,     // 2
        InTransit,      // 3
        OutForDelivery, // 4
        Arrived,        // 5
        Approved,       // 6
        Executed,       // 7
        Disputed,       // 8 - side state, only reachable from Arrived
        Cancelled       // 9 - side state
    }

    struct ShipmentContract {
        address receiver;        // the orderer's backend-custodied address
        bytes32 vendorRef;       // hash of the vendor id
        bytes32 destinationHash; // hash of the delivery destination string
        bytes32 orderHash;       // hash of the accepted items/qty/prices — tamper-evident terms
        uint256 amount;          // informational — total order amount (smallest currency unit)
        bytes32 paymentRef;      // hash of the Stripe PaymentIntent id (Phase 4; zero until then)
        Status status;
        uint256 createdAt;
        uint256 updatedAt;
        uint32 checkpointCount;
        bool exists;
    }

    mapping(bytes32 => ShipmentContract) private _contracts;

    event ContractCreated(bytes32 indexed orderId, address indexed receiver, bytes32 vendorRef, bytes32 orderHash, uint256 amount, uint256 ts);
    event StatusChanged(bytes32 indexed orderId, Status from, Status to, uint256 ts);
    event CheckpointRecorded(bytes32 indexed orderId, string location, bytes32 noteHash, uint8 actorType, uint256 ts);
    event ArrivalConfirmed(bytes32 indexed orderId, uint256 ts);
    event ReceiptApproved(bytes32 indexed orderId, uint256 ts);
    event ContractExecuted(bytes32 indexed orderId, uint256 ts);
    event Disputed(bytes32 indexed orderId, bytes32 reasonHash, uint256 ts);
    event DisputeResolved(bytes32 indexed orderId, Status resolution, uint256 ts);
    event Cancelled(bytes32 indexed orderId, uint256 ts);

    constructor(address admin, address logisticsBackend) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(LOGISTICS_ROLE, logisticsBackend);
    }

    modifier onlyReceiver(bytes32 orderId) {
        require(_contracts[orderId].exists, "ShipmentEscrow: no such contract");
        require(_contracts[orderId].receiver == msg.sender, "ShipmentEscrow: not receiver");
        _;
    }

    function createContract(
        bytes32 orderId,
        address receiver,
        bytes32 vendorRef,
        bytes32 destinationHash,
        bytes32 orderHash,
        uint256 amount,
        bytes32 paymentRef
    ) external onlyRole(LOGISTICS_ROLE) {
        require(!_contracts[orderId].exists, "ShipmentEscrow: already exists");
        require(receiver != address(0), "ShipmentEscrow: receiver required");
        _contracts[orderId] = ShipmentContract({
            receiver: receiver,
            vendorRef: vendorRef,
            destinationHash: destinationHash,
            orderHash: orderHash,
            amount: amount,
            paymentRef: paymentRef,
            status: Status.Preparing,
            createdAt: block.timestamp,
            updatedAt: block.timestamp,
            checkpointCount: 0,
            exists: true
        });
        emit ContractCreated(orderId, receiver, vendorRef, orderHash, amount, block.timestamp);
        emit StatusChanged(orderId, Status.None, Status.Preparing, block.timestamp);
    }

    function recordCheckpoint(
        bytes32 orderId,
        Status newStatus,
        string calldata location,
        bytes32 noteHash,
        uint8 actorType
    ) external onlyRole(LOGISTICS_ROLE) {
        ShipmentContract storage c = _contracts[orderId];
        require(c.exists, "ShipmentEscrow: no such contract");
        require(
            c.status == Status.Preparing || c.status == Status.Dispatched ||
            c.status == Status.InTransit || c.status == Status.OutForDelivery,
            "ShipmentEscrow: not in a shippable state"
        );
        require(
            newStatus == Status.Dispatched || newStatus == Status.InTransit || newStatus == Status.OutForDelivery,
            "ShipmentEscrow: illegal checkpoint status"
        );
        require(uint8(newStatus) >= uint8(c.status), "ShipmentEscrow: cannot move backward");

        Status from = c.status;
        c.status = newStatus;
        c.updatedAt = block.timestamp;
        c.checkpointCount += 1;
        emit CheckpointRecorded(orderId, location, noteHash, actorType, block.timestamp);
        if (newStatus != from) {
            emit StatusChanged(orderId, from, newStatus, block.timestamp);
        }
    }

    function confirmArrival(bytes32 orderId, bytes32 destinationHash) external onlyReceiver(orderId) {
        ShipmentContract storage c = _contracts[orderId];
        require(
            c.status == Status.OutForDelivery || c.status == Status.InTransit,
            "ShipmentEscrow: not out for delivery"
        );
        require(c.destinationHash == destinationHash, "ShipmentEscrow: destination mismatch");

        Status from = c.status;
        c.status = Status.Arrived;
        c.updatedAt = block.timestamp;
        emit ArrivalConfirmed(orderId, block.timestamp);
        emit StatusChanged(orderId, from, Status.Arrived, block.timestamp);
    }

    /// @notice Approval and execution happen atomically — there is no other
    /// path to Executed than Arrived -> Approved -> (immediately) Executed.
    function approveReceipt(bytes32 orderId) external nonReentrant onlyReceiver(orderId) {
        ShipmentContract storage c = _contracts[orderId];
        require(c.status == Status.Arrived, "ShipmentEscrow: not arrived");

        c.status = Status.Approved;
        c.updatedAt = block.timestamp;
        emit ReceiptApproved(orderId, block.timestamp);
        emit StatusChanged(orderId, Status.Arrived, Status.Approved, block.timestamp);

        c.status = Status.Executed;
        c.updatedAt = block.timestamp;
        emit ContractExecuted(orderId, block.timestamp);
        emit StatusChanged(orderId, Status.Approved, Status.Executed, block.timestamp);
    }

    function dispute(bytes32 orderId, bytes32 reasonHash) external onlyReceiver(orderId) {
        ShipmentContract storage c = _contracts[orderId];
        require(c.status == Status.Arrived, "ShipmentEscrow: can only dispute after arrival");

        Status from = c.status;
        c.status = Status.Disputed;
        c.updatedAt = block.timestamp;
        emit Disputed(orderId, reasonHash, block.timestamp);
        emit StatusChanged(orderId, from, Status.Disputed, block.timestamp);
    }

    function resolveDispute(bytes32 orderId, Status resolution) external onlyRole(ADMIN_ROLE) {
        ShipmentContract storage c = _contracts[orderId];
        require(c.exists, "ShipmentEscrow: no such contract");
        require(c.status == Status.Disputed, "ShipmentEscrow: not disputed");
        require(
            resolution == Status.Arrived || resolution == Status.Cancelled || resolution == Status.Executed,
            "ShipmentEscrow: illegal resolution"
        );

        Status from = c.status;
        c.status = resolution;
        c.updatedAt = block.timestamp;
        emit DisputeResolved(orderId, resolution, block.timestamp);
        emit StatusChanged(orderId, from, resolution, block.timestamp);
        if (resolution == Status.Executed) {
            emit ContractExecuted(orderId, block.timestamp);
        }
    }

    function cancel(bytes32 orderId) external onlyRole(ADMIN_ROLE) {
        ShipmentContract storage c = _contracts[orderId];
        require(c.exists, "ShipmentEscrow: no such contract");
        require(
            c.status == Status.Preparing || c.status == Status.Dispatched ||
            c.status == Status.InTransit || c.status == Status.OutForDelivery,
            "ShipmentEscrow: cannot cancel in this state"
        );

        Status from = c.status;
        c.status = Status.Cancelled;
        c.updatedAt = block.timestamp;
        emit Cancelled(orderId, block.timestamp);
        emit StatusChanged(orderId, from, Status.Cancelled, block.timestamp);
    }

    function getContract(bytes32 orderId)
        external
        view
        returns (
            address receiver,
            bytes32 vendorRef,
            bytes32 destinationHash,
            bytes32 orderHash,
            uint256 amount,
            bytes32 paymentRef,
            Status status,
            uint256 createdAt,
            uint256 updatedAt,
            uint32 checkpointCount
        )
    {
        ShipmentContract storage c = _contracts[orderId];
        require(c.exists, "ShipmentEscrow: no such contract");
        return (
            c.receiver, c.vendorRef, c.destinationHash, c.orderHash,
            c.amount, c.paymentRef, c.status, c.createdAt, c.updatedAt, c.checkpointCount
        );
    }

    function contractExists(bytes32 orderId) external view returns (bool) {
        return _contracts[orderId].exists;
    }
}
