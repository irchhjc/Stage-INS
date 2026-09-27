param(
    [string]$OutputRoot = "."
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$privateConfig = Join-Path $projectRoot ".local-server.ps1"
if (-not (Test-Path -LiteralPath $privateConfig)) {
    throw "Configuration absente : $privateConfig"
}

. $privateConfig
if (-not $env:DATABASE_URL -or -not $env:DATABASE_URL.StartsWith("postgresql")) {
    throw "DATABASE_URL PostgreSQL absente de .local-server.ps1"
}

$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if (-not $pgDump) {
    $pgDump = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
}
if (-not $pgDump) {
    throw "pg_dump est introuvable. Installez les outils client PostgreSQL ou ajoutez-les au PATH."
}

$databaseUrl = $env:DATABASE_URL.Replace("postgresql+psycopg://", "postgresql://")
$uri = [Uri]$databaseUrl
$credentials = $uri.UserInfo.Split(":", 2)
$databaseUser = [Uri]::UnescapeDataString($credentials[0])
$databasePassword = [Uri]::UnescapeDataString($credentials[1])
$databaseName = $uri.AbsolutePath.TrimStart("/")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bundle = Join-Path (Resolve-Path $OutputRoot) "migration_bundle_$timestamp"
New-Item -ItemType Directory -Path $bundle | Out-Null

$previousPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = $databasePassword
    & $pgDump.Source `
        --host $uri.Host `
        --port $uri.Port `
        --username $databaseUser `
        --dbname $databaseName `
        --format custom `
        --no-owner `
        --file (Join-Path $bundle "postgres.dump")
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump a échoué avec le code $LASTEXITCODE."
    }
}
finally {
    $env:PGPASSWORD = $previousPassword
}

$instanceFolder = Join-Path $projectRoot "instance"
if (-not (Test-Path -LiteralPath $instanceFolder)) {
    throw "Dossier instance absent : $instanceFolder"
}
& tar.exe -czf (Join-Path $bundle "instance.tar.gz") -C $instanceFolder .
if ($LASTEXITCODE -ne 0) {
    throw "La création de l'archive instance a échoué."
}

Write-Host "Paquet de migration créé : $bundle"
Write-Host "- postgres.dump"
Write-Host "- instance.tar.gz"
