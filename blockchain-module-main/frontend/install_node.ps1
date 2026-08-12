$ErrorActionPreference = "Stop"
Write-Host "Downloading Node.js..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.11.1/node-v20.11.1-win-x64.zip" -OutFile "node.zip" -UseBasicParsing
Write-Host "Extracting Node.js..."
Expand-Archive -Path "node.zip" -DestinationPath "." -Force
Write-Host "Done!"
