# Daily copy-trading startup (Windows PowerShell equivalent of morning.sh).
# Refreshes Zerodha tokens (they expire ~6 AM IST), re-syncs instruments,
# restarts the ticker/workers, then runs preflight.
#
# Zerodha login is interactive, so this pauses for you to paste each account's
# request_token (copied from the redirect URL after logging in).
#
# Usage:
#   .\morning.ps1
#   .\morning.ps1 -Master mom_zerodha -Copy my_zerodha

param(
    [string]$Master = "mom_zerodha",
    [string]$Copy   = "my_zerodha"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Invoke-MC {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$Args)
    docker compose exec -T web python manage.py @Args
}

function Login-Account {
    param([string]$Acct)
    Write-Host ""
    Write-Host ">> Login URL for '$Acct' - open it, log in, then copy the request_token" -ForegroundColor Cyan
    Write-Host "   from the redirect URL (the ?request_token=XXXX part):" -ForegroundColor Cyan
    Write-Host ""
    Invoke-MC kite_login --account $Acct
    Write-Host ""
    $token = Read-Host "   Paste request_token for '$Acct'"
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "No token entered for '$Acct'."
    }
    Invoke-MC kite_login --account $Acct --request-token $token
}

Write-Host ">> Ensuring the stack is up..."
docker compose up -d | Out-Null

Login-Account $Master
Login-Account $Copy

Write-Host ""
Write-Host ">> Syncing instruments (lot sizes) from '$Master'..."
Invoke-MC kite_sync_instruments --account $Master

Write-Host ""
Write-Host ">> Restarting ticker + workers to pick up fresh tokens..."
docker compose restart kite_ticker celery_worker celery_beat | Out-Null

Write-Host ""
Write-Host ">> Running preflight checklist..."
try { Invoke-MC preflight } catch { }

Write-Host ""
Write-Host ">> Done. Dashboard: http://localhost:5173/dashboard  (or http://localhost:8000/dashboard/)"
Write-Host "   Live orders are controlled by COPYTRADING_LIVE_ORDERS in .env."
