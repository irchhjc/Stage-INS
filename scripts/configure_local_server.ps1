param(
    [string]$DatabaseUrl,
    [string]$DatabaseUser = "dsf_app",
    [string]$DatabaseName = "dsf_control",
    [string]$DatabaseHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$DatabasePort = 5432,
    [SecureString]$DatabasePassword,
    [string]$AdminUsername = "irch",
    [SecureString]$AdminPassword,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8080,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $projectRoot ".local-server.ps1"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if ((Test-Path -LiteralPath $configPath) -and -not $Force) {
    throw "Le serveur est deja configure. Utilisez start_local_server.ps1. L'option -Force recree la cle et deconnecte toutes les sessions actives."
}
function Get-PlainTextFromSecureString([SecureString]$SecureValue) {
    $valuePointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($valuePointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($valuePointer)
    }
}

if (-not $DatabaseUrl) {
    if (-not $DatabasePassword) {
        $DatabasePassword = Read-Host "Mot de passe PostgreSQL du role $DatabaseUser" -AsSecureString
    }
    $plainDatabasePassword = Get-PlainTextFromSecureString $DatabasePassword
    $encodedDatabaseUser = [Uri]::EscapeDataString($DatabaseUser)
    $encodedDatabasePassword = [Uri]::EscapeDataString($plainDatabasePassword)
    $encodedDatabaseName = [Uri]::EscapeDataString($DatabaseName)
    $DatabaseUrl = "postgresql+psycopg://${encodedDatabaseUser}:${encodedDatabasePassword}@${DatabaseHost}:$DatabasePort/$encodedDatabaseName"
}
elseif ($DatabaseUrl -notmatch '^postgres(ql)?(\+psycopg)?://') {
    throw "DatabaseUrl doit etre une URL PostgreSQL (postgresql://...)."
}
elseif ($DatabaseUrl -match '(?i)ChoisissezUnMotDePasse|VOTRE_MOT_DE_PASSE|REMPLACEZ') {
    throw "L'URL contient encore un mot de passe d'exemple. Utilisez le vrai mot de passe PostgreSQL."
}

if (-not $AdminPassword) {
    $AdminPassword = Read-Host "Mot de passe initial de l'administrateur (10 caracteres minimum)" -AsSecureString
}
$plainAdminPassword = Get-PlainTextFromSecureString $AdminPassword

if ($AdminUsername -cne $AdminUsername.ToLowerInvariant()) {
    throw "Le nom administrateur doit etre entierement en minuscules."
}
if ($plainAdminPassword.Length -lt 10) {
    throw "Le mot de passe administrateur doit contenir au moins 10 caracteres."
}

$secretBytes = New-Object byte[] 48
$randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $randomGenerator.GetBytes($secretBytes)
}
finally {
    $randomGenerator.Dispose()
}
$secretKey = -join ($secretBytes | ForEach-Object { $_.ToString("x2") })

function ConvertTo-SingleQuotedPowerShellString([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

$configLines = @(
    '# Configuration privee du serveur DSF local. Ne pas envoyer ce fichier.',
    '$env:SECRET_KEY = ' + (ConvertTo-SingleQuotedPowerShellString $secretKey),
    '$env:DATABASE_URL = ' + (ConvertTo-SingleQuotedPowerShellString $DatabaseUrl),
    '$env:INITIAL_ADMIN_USERNAME = ' + (ConvertTo-SingleQuotedPowerShellString $AdminUsername),
    '$env:INITIAL_ADMIN_PASSWORD = ' + (ConvertTo-SingleQuotedPowerShellString $plainAdminPassword),
    '$env:SESSION_LIFETIME_HOURS = ''168''',
    '$env:SESSION_COOKIE_SECURE = ''false''',
    '$env:LOCAL_SERVER_PORT = ' + (ConvertTo-SingleQuotedPowerShellString $Port.ToString())
)

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creation de l'environnement Python..." -ForegroundColor Cyan
    & py -3 -m venv (Join-Path $projectRoot ".venv")
}

Write-Host "Installation des dependances..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "L'installation des dependances a echoue."
}

# Tester les nouvelles valeurs dans ce processus avant d'ecrire le fichier prive.
$env:SECRET_KEY = $secretKey
$env:DATABASE_URL = $DatabaseUrl
$env:INITIAL_ADMIN_USERNAME = $AdminUsername
$env:INITIAL_ADMIN_PASSWORD = $plainAdminPassword
$env:SESSION_LIFETIME_HOURS = "168"
$env:SESSION_COOKIE_SECURE = "false"
$env:LOCAL_SERVER_PORT = $Port.ToString()

Write-Host "Initialisation et verification de la base PostgreSQL..." -ForegroundColor Cyan
Push-Location $projectRoot
try {
    & $venvPython -c "from run import app; app.app_context().push(); print('SGBD actif :', app.extensions['sqlalchemy'].engine.dialect.name)"
    if ($LASTEXITCODE -ne 0) {
        throw "Connexion ou initialisation PostgreSQL impossible. Verifiez le nom du role, son mot de passe et la base."
    }
}
finally {
    Pop-Location
}

Set-Content -LiteralPath $configPath -Value $configLines -Encoding UTF8
Write-Host "Configuration locale creee avec succes." -ForegroundColor Green
Write-Host "Demarrez le serveur avec : .\scripts\start_local_server.ps1"
Write-Host "Le fichier prive .local-server.ps1 est exclu de Git."
