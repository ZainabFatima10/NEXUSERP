require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

// NEXUS ERP — ShipmentEscrow Hardhat project.
// Local/demo default: the built-in `hardhat` network (in-process, instant,
// no faucet). Public proof: Sepolia testnet via SEPOLIA_RPC_URL (a free
// Alchemy/Chainstack/public RPC) + SEPOLIA_PRIVATE_KEY (a throwaway dev key
// funded only from free faucets — never a real-value key). See
// SHIPMENT_ESCROW.md for the full local <-> Sepolia switching instructions.

const SEPOLIA_RPC_URL = process.env.SEPOLIA_RPC_URL || "";
const SEPOLIA_PRIVATE_KEY = process.env.SEPOLIA_PRIVATE_KEY || "";

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },
  networks: {
    hardhat: {
      chainId: 31337,
    },
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 31337,
    },
    sepolia: {
      url: SEPOLIA_RPC_URL || "https://rpc.sepolia.org",
      accounts: SEPOLIA_PRIVATE_KEY ? [SEPOLIA_PRIVATE_KEY] : [],
      chainId: 11155111,
    },
  },
  paths: {
    artifacts: "./artifacts-out",
  },
};
