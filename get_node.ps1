$dest = "$env:USERPROFILE\.nodejs"
if (-not (Test-Path $dest)) {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
}
$zipPath = "$dest\node.zip"
$extractFolder = "$dest\node-v20.18.0-win-x64"

if (-not (Test-Path "$extractFolder\node.exe")) {
    Write-Host "Downloading portable Node.js LTS..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.18.0/node-v20.18.0-win-x64.zip" -OutFile $zipPath
    Write-Host "Extracting..."
    Expand-Archive -Path $zipPath -DestinationPath $dest -Force
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    Write-Host "Node.js ready at $extractFolder"
} else {
    Write-Host "Node.js already present at $extractFolder"
}

# Verify
& "$extractFolder\node.exe" --version
& "$extractFolder\npm.cmd" --version
