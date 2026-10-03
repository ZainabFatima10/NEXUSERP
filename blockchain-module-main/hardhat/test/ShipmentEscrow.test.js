const { expect } = require("chai");
const { ethers } = require("hardhat");
const { anyValue } = require("@nomicfoundation/hardhat-chai-matchers/withArgs");

// Status enum mirrors the Solidity contract exactly — keep in sync.
const Status = {
  None: 0, Preparing: 1, Dispatched: 2, InTransit: 3, OutForDelivery: 4,
  Arrived: 5, Approved: 6, Executed: 7, Disputed: 8, Cancelled: 9,
};

function hash(s) {
  return ethers.keccak256(ethers.toUtf8Bytes(s));
}

describe("ShipmentEscrow", function () {
  let escrow, admin, logistics, receiver, otherReceiver, stranger;
  const orderId = hash("ORD-TEST-0001");
  const vendorRef = hash("vendor-1");
  const destinationHash = hash("Main Warehouse, Lahore");
  const orderHash = hash("items-qty-prices-snapshot");
  const amount = 1850000; // smallest currency unit, informational
  const paymentRef = hash("pi_test_123");

  beforeEach(async function () {
    [admin, logistics, receiver, otherReceiver, stranger] = await ethers.getSigners();
    const Factory = await ethers.getContractFactory("ShipmentEscrow");
    escrow = await Factory.deploy(admin.address, logistics.address);
    await escrow.waitForDeployment();
  });

  function createDefault() {
    return escrow.connect(logistics).createContract(
      orderId, receiver.address, vendorRef, destinationHash, orderHash, amount, paymentRef
    );
  }

  describe("createContract", function () {
    it("creates a Preparing contract and emits events", async function () {
      await expect(createDefault())
        .to.emit(escrow, "ContractCreated")
        .withArgs(orderId, receiver.address, vendorRef, orderHash, amount, anyValue)
        .and.to.emit(escrow, "StatusChanged")
        .withArgs(orderId, Status.None, Status.Preparing, anyValue);

      const c = await escrow.getContract(orderId);
      expect(c.status).to.equal(Status.Preparing);
      expect(c.receiver).to.equal(receiver.address);
    });

    it("reverts on duplicate orderId", async function () {
      await createDefault();
      await expect(createDefault()).to.be.revertedWith("ShipmentEscrow: already exists");
    });

    it("reverts for a non-LOGISTICS_ROLE caller", async function () {
      await expect(
        escrow.connect(stranger).createContract(orderId, receiver.address, vendorRef, destinationHash, orderHash, amount, paymentRef)
      ).to.be.revertedWithCustomError(escrow, "AccessControlUnauthorizedAccount");
    });

    it("reverts with a zero-address receiver", async function () {
      await expect(
        escrow.connect(logistics).createContract(orderId, ethers.ZeroAddress, vendorRef, destinationHash, orderHash, amount, paymentRef)
      ).to.be.revertedWith("ShipmentEscrow: receiver required");
    });
  });

  describe("recordCheckpoint", function () {
    beforeEach(createDefault);

    it("moves Preparing -> Dispatched -> InTransit -> OutForDelivery", async function () {
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "Vendor Warehouse", hash("picked up"), 0);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Dispatched);

      await escrow.connect(logistics).recordCheckpoint(orderId, Status.InTransit, "Lahore Hub", hash("in transit"), 0);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.InTransit);

      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "Local depot", hash("out for delivery"), 0);
      const c = await escrow.getContract(orderId);
      expect(c.status).to.equal(Status.OutForDelivery);
      expect(c.checkpointCount).to.equal(3);
    });

    it("allows InTransit to repeat with a new checkpoint (no backward move)", async function () {
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.InTransit, "B", hash("b"), 0);
      await expect(
        escrow.connect(logistics).recordCheckpoint(orderId, Status.InTransit, "C", hash("c"), 0)
      ).to.not.be.reverted;
      expect((await escrow.getContract(orderId)).checkpointCount).to.equal(3);
    });

    it("reverts moving backward (OutForDelivery -> Dispatched)", async function () {
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "B", hash("b"), 0);
      await expect(
        escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "C", hash("c"), 0)
      ).to.be.revertedWith("ShipmentEscrow: cannot move backward");
    });

    it("reverts for a non-LOGISTICS_ROLE caller", async function () {
      await expect(
        escrow.connect(stranger).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0)
      ).to.be.revertedWithCustomError(escrow, "AccessControlUnauthorizedAccount");
    });

    it("reverts an illegal checkpoint status (e.g. Arrived via recordCheckpoint)", async function () {
      await expect(
        escrow.connect(logistics).recordCheckpoint(orderId, Status.Arrived, "A", hash("a"), 0)
      ).to.be.revertedWith("ShipmentEscrow: illegal checkpoint status");
    });

    it("reverts once the contract has moved past a shippable state", async function () {
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "B", hash("b"), 0);
      await escrow.connect(receiver).confirmArrival(orderId, destinationHash);
      await expect(
        escrow.connect(logistics).recordCheckpoint(orderId, Status.InTransit, "C", hash("c"), 0)
      ).to.be.revertedWith("ShipmentEscrow: not in a shippable state");
    });
  });

  describe("confirmArrival", function () {
    beforeEach(async function () {
      await createDefault();
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "B", hash("b"), 0);
    });

    it("receiver can confirm arrival with the matching destination hash", async function () {
      await expect(escrow.connect(receiver).confirmArrival(orderId, destinationHash))
        .to.emit(escrow, "ArrivalConfirmed").withArgs(orderId, anyValue);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Arrived);
    });

    it("reverts for a wrong destinationHash", async function () {
      await expect(
        escrow.connect(receiver).confirmArrival(orderId, hash("wrong address"))
      ).to.be.revertedWith("ShipmentEscrow: destination mismatch");
    });

    it("reverts for a non-receiver caller (another orderer)", async function () {
      await expect(
        escrow.connect(otherReceiver).confirmArrival(orderId, destinationHash)
      ).to.be.revertedWith("ShipmentEscrow: not receiver");
    });

    it("reverts for a non-receiver caller (even an admin/logistics account)", async function () {
      await expect(
        escrow.connect(admin).confirmArrival(orderId, destinationHash)
      ).to.be.revertedWith("ShipmentEscrow: not receiver");
      await expect(
        escrow.connect(logistics).confirmArrival(orderId, destinationHash)
      ).to.be.revertedWith("ShipmentEscrow: not receiver");
    });

    it("reverts before dispatch (still Preparing)", async function () {
      const freshOrderId = hash("ORD-TEST-0002");
      await escrow.connect(logistics).createContract(freshOrderId, receiver.address, vendorRef, destinationHash, orderHash, amount, paymentRef);
      await expect(
        escrow.connect(receiver).confirmArrival(freshOrderId, destinationHash)
      ).to.be.revertedWith("ShipmentEscrow: not out for delivery");
    });
  });

  describe("approveReceipt — approval and execution", function () {
    beforeEach(async function () {
      await createDefault();
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "B", hash("b"), 0);
    });

    it("reverts approval before arrival is confirmed", async function () {
      await expect(
        escrow.connect(receiver).approveReceipt(orderId)
      ).to.be.revertedWith("ShipmentEscrow: not arrived");
    });

    it("execution is impossible without arrival + approval (no direct path)", async function () {
      // There is no function that can reach Executed except approveReceipt
      // after Arrived — demonstrated by the previous test's revert, and by
      // there being no `execute()` entrypoint at all in the ABI.
      expect(escrow.interface.getFunction("execute")).to.be.null;
    });

    it("approve after arrival executes the contract atomically, in one call", async function () {
      await escrow.connect(receiver).confirmArrival(orderId, destinationHash);
      await expect(escrow.connect(receiver).approveReceipt(orderId))
        .to.emit(escrow, "ReceiptApproved").withArgs(orderId, anyValue)
        .and.to.emit(escrow, "ContractExecuted").withArgs(orderId, anyValue);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Executed);
    });

    it("reverts a double approval", async function () {
      await escrow.connect(receiver).confirmArrival(orderId, destinationHash);
      await escrow.connect(receiver).approveReceipt(orderId);
      await expect(
        escrow.connect(receiver).approveReceipt(orderId)
      ).to.be.revertedWith("ShipmentEscrow: not arrived");
    });

    it("reverts approval from a non-receiver", async function () {
      await escrow.connect(receiver).confirmArrival(orderId, destinationHash);
      await expect(
        escrow.connect(otherReceiver).approveReceipt(orderId)
      ).to.be.revertedWith("ShipmentEscrow: not receiver");
    });
  });

  describe("dispute / resolveDispute", function () {
    beforeEach(async function () {
      await createDefault();
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "B", hash("b"), 0);
      await escrow.connect(receiver).confirmArrival(orderId, destinationHash);
    });

    it("receiver can dispute only after arrival", async function () {
      await expect(escrow.connect(receiver).dispute(orderId, hash("damaged goods")))
        .to.emit(escrow, "Disputed").withArgs(orderId, hash("damaged goods"), anyValue);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Disputed);
    });

    it("reverts dispute from a non-receiver", async function () {
      await expect(
        escrow.connect(stranger).dispute(orderId, hash("x"))
      ).to.be.revertedWith("ShipmentEscrow: not receiver");
    });

    it("admin resolves back to Arrived", async function () {
      await escrow.connect(receiver).dispute(orderId, hash("damaged goods"));
      await escrow.connect(admin).resolveDispute(orderId, Status.Arrived);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Arrived);
    });

    it("admin resolves to Cancelled", async function () {
      await escrow.connect(receiver).dispute(orderId, hash("damaged goods"));
      await escrow.connect(admin).resolveDispute(orderId, Status.Cancelled);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Cancelled);
    });

    it("admin resolves to Executed (documented override) and emits ContractExecuted", async function () {
      await escrow.connect(receiver).dispute(orderId, hash("damaged goods"));
      await expect(escrow.connect(admin).resolveDispute(orderId, Status.Executed))
        .to.emit(escrow, "ContractExecuted").withArgs(orderId, anyValue);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Executed);
    });

    it("reverts resolveDispute from a non-ADMIN_ROLE caller", async function () {
      await escrow.connect(receiver).dispute(orderId, hash("damaged goods"));
      await expect(
        escrow.connect(logistics).resolveDispute(orderId, Status.Arrived)
      ).to.be.revertedWithCustomError(escrow, "AccessControlUnauthorizedAccount");
    });

    it("reverts resolveDispute with an illegal resolution target", async function () {
      await escrow.connect(receiver).dispute(orderId, hash("damaged goods"));
      await expect(
        escrow.connect(admin).resolveDispute(orderId, Status.Dispatched)
      ).to.be.revertedWith("ShipmentEscrow: illegal resolution");
    });

    it("reverts resolveDispute when not currently disputed", async function () {
      const freshOrderId = hash("ORD-TEST-0003");
      await escrow.connect(logistics).createContract(freshOrderId, receiver.address, vendorRef, destinationHash, orderHash, amount, paymentRef);
      await expect(
        escrow.connect(admin).resolveDispute(freshOrderId, Status.Cancelled)
      ).to.be.revertedWith("ShipmentEscrow: not disputed");
    });
  });

  describe("cancel", function () {
    it("admin can cancel a Preparing contract", async function () {
      await createDefault();
      await expect(escrow.connect(admin).cancel(orderId))
        .to.emit(escrow, "Cancelled").withArgs(orderId, anyValue);
      expect((await escrow.getContract(orderId)).status).to.equal(Status.Cancelled);
    });

    it("reverts cancel from a non-ADMIN_ROLE caller", async function () {
      await createDefault();
      await expect(
        escrow.connect(logistics).cancel(orderId)
      ).to.be.revertedWithCustomError(escrow, "AccessControlUnauthorizedAccount");
    });

    it("reverts cancel once Arrived", async function () {
      await createDefault();
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.Dispatched, "A", hash("a"), 0);
      await escrow.connect(logistics).recordCheckpoint(orderId, Status.OutForDelivery, "B", hash("b"), 0);
      await escrow.connect(receiver).confirmArrival(orderId, destinationHash);
      await expect(
        escrow.connect(admin).cancel(orderId)
      ).to.be.revertedWith("ShipmentEscrow: cannot cancel in this state");
    });
  });
});
