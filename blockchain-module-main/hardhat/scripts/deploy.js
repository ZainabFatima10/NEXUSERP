// Deploys ShipmentEscrow and writes its address + ABI to a JSON file the
// Python backend reads directly (shipment_chain_service.py) — no shared
// node_modules or build step needed between the two halves of the project.
//
// Usage:
//   npx hardhat run scripts/deploy.js --network hardhat    (in-process, for tests)
//   npx hardhat run scripts/deploy.js --network localhost  (against `npx hardhat node`)
//   npx hardhat run scripts/deploy.js --network sepolia    (needs SEPOLIA_RPC_URL + SEPOLIA_PRIVATE_KEY in .env)
const fs = require("fs");
const path = require("path");
const { ethers, network } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();

  // The same account is both the initial ADMIN_ROLE holder and the
  // LOGISTICS_ROLE backend service account for local/dev deploys — on
  // Sepolia you'd typically grant LOGISTICS_ROLE to a separate hot wallet
  // via grantRole() after deploy and keep the admin key colder.
  const logisticsBackend = process.env.LOGISTICS_BACKEND_ADDRESS || deployer.address;

  console.log(`Deploying ShipmentEscrow to ${network.name} as ${deployer.address}...`);
  const Factory = await ethers.getContractFactory("ShipmentEscrow");
  const escrow = await Factory.deploy(deployer.address, logisticsBackend);
  await escrow.waitForDeployment();

  const address = await escrow.getAddress();
  const artifact = require("../artifacts-out/contracts/ShipmentEscrow.sol/ShipmentEscrow.json");

  const outDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, `${network.name}.json`);
  fs.writeFileSync(
    outFile,
    JSON.stringify(
      {
        network: network.name,
        chainId: network.config.chainId,
        address,
        deployer: deployer.address,
        logisticsBackend,
        abi: artifact.abi,
        deployedAt: new Date().toISOString(),
      },
      null,
      2
    )
  );

  console.log(`ShipmentEscrow deployed at ${address}`);
  console.log(`Wrote deployment info to ${outFile}`);
  console.log(`Set CONTRACT_ADDRESS=${address} and CHAIN_NETWORK=${network.name} in ai-module/.env`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
