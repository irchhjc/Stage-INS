param(
    [ValidateRange(1024, 65535)]
    [int]$Port
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $projectRoot ".local-server.ps1"
$waitress = Join-Path $projectRoot ".venv\Scripts\waitress-serve.exe"

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Configuration absente. Executez d'abord scripts\configure_local_server.ps1."
}
if (-not (Test-Path -LiteralPath $waitress)) {
    throw "Waitress est absent. Relancez scripts\configure_local_server.ps1."
}

. $configPath
if (-not $PSBoundParameters.ContainsKey("Port")) {
    $Port = if ($env:LOCAL_SERVER_PORT) { [int]$env:LOCAL_SERVER_PORT } else { 8080 }
}

$lanAddress = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
    Where-Object {
        $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
        -not [System.Net.IPAddress]::IsLoopback($_) -and
        $_.IPAddressToString -notlike "169.254.*"
    } |
    Select-Object -First 1 -ExpandProperty IPAddressToString

Write-Host "Serveur DSF en cours de demarrage..." -ForegroundColor Cyan
Write-Host "Sur cet ordinateur : http://127.0.0.1:$Port"
if ($lanAddress) {
    Write-Host "Lien a communiquer aux controleurs : http://${lanAddress}:$Port" -ForegroundColor Green
} else {
    Write-Warning "Adresse reseau introuvable. Verifiez la connexion Wi-Fi ou Ethernet."
}
Write-Host "Gardez cette fenetre ouverte. Ctrl+C arrete le serveur."

Push-Location $projectRoot
try {
    & $waitress --listen="0.0.0.0:$Port" --threads=8 --channel-timeout=300 run:app
}
finally {
    Pop-Location
}
