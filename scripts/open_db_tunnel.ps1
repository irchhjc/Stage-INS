<#
.SYNOPSIS
    Ouvre un tunnel SSH vers la base PostgreSQL du VPS pour pgAdmin.

.DESCRIPTION
    Relie le port local 5433 au port 5432 du VPS (qui n'écoute que sur 127.0.0.1).
    Laissez cette fenêtre ouverte pendant que vous utilisez pgAdmin (Ctrl+C pour fermer).
    Dans pgAdmin : Host = localhost, Port = 5433.

.EXAMPLE
    .\scripts\open_db_tunnel.ps1
    .\scripts\open_db_tunnel.ps1 -User dsfdeploy -LocalPort 5434
#>
param(
    [string]$Server = "92.113.26.206",
    [string]$User = "root",
    [int]$LocalPort = 5433,
    [string]$KeyFile = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "ssh est introuvable. Activez « Client OpenSSH » dans Paramètres > Applications > Fonctionnalités facultatives."
}

$listener = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "Le port local $LocalPort est déjà utilisé. Relancez avec -LocalPort 5434 (et utilisez ce port dans pgAdmin)."
}

$arguments = @(
    "-N",
    "-L", "$($LocalPort):127.0.0.1:5432",
    "-o", "ServerAliveInterval=30",
    "-o", "ExitOnForwardFailure=yes"
)
if ($KeyFile) { $arguments += @("-i", $KeyFile) }
$arguments += "$User@$Server"

Write-Host "Tunnel ouvert : localhost:$LocalPort -> PostgreSQL du VPS ($Server)."
Write-Host "Dans pgAdmin : Host = localhost, Port = $LocalPort. Ctrl+C pour fermer."
& ssh @arguments
