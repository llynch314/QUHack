<#
AttuneMind wearable helper for Windows (no `make` needed). Run from the repo root:

  .\scripts\wearable.ps1 setup            venv + dependencies + backend/.env ready for demo testing
  .\scripts\wearable.ps1 test             run the wearable test suite (pytest)
  .\scripts\wearable.ps1 run [-Port 5050] start the app with DEMO_MODE=1 and DEV_LOGIN=1, open My Watch
                                          (port 5000 is reserved by Windows on some PCs, so 5050 is the default)
  .\scripts\wearable.ps1 sim <scenario>   push a scenario straight into the DB for the demo patient
                                          (baseline, exercise, stress_spike, sustained_distress, fall, cardiac_warning, recovery)
  .\scripts\wearable.ps1 send -Url <url> -Token <token> [-Hr 72]
                                          send one reading like the iPhone Shortcut does
  .\scripts\wearable.ps1 tunnel           start a Cloudflare quick tunnel to the app (HTTPS URL for the phone)
  .\scripts\wearable.ps1 status           show the wearable configuration
  .\scripts\wearable.ps1 reset-db         delete the local SQLite database (asks first)

If PowerShell blocks the script:  powershell -ExecutionPolicy Bypass -File .\scripts\wearable.ps1 <command>
#>
param(
    [Parameter(Position = 0)][string]$Command = 'help',
    [Parameter(Position = 1)][string]$Scenario = 'baseline',
    [string]$Url = '',
    [int]$Port = 5050,
    [string]$Token = '',
    [double]$Hr = 72,
    [int]$Patient = 0
)
# 'Continue' so Python warnings on stderr aren't treated as fatal by Windows PowerShell 5.1
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Py = Join-Path $Backend '.venv\Scripts\python.exe'
if (-not $Url) { $Url = "http://127.0.0.1:$Port" }

function Need-Venv {
    if (-not (Test-Path $Py)) { throw 'No virtual environment yet. Run:  .\scripts\wearable.ps1 setup' }
}

switch ($Command) {
    'setup' {
        if (-not (Test-Path $Py)) { Push-Location $Backend; try { python -m venv .venv } finally { Pop-Location } }
        & $Py -m pip install --upgrade pip -q
        & $Py -m pip install -r (Join-Path $Backend 'requirements.txt')
        Push-Location $Backend; try { & $Py -m wearable.devtool env } finally { Pop-Location }
        Write-Host "`nSetup done. Next:  .\scripts\wearable.ps1 test   then   .\scripts\wearable.ps1 run" -ForegroundColor Green
    }
    'test' {
        Need-Venv
        Push-Location $Root; try { & $Py -m pytest backend/wearable/tests -q } finally { Pop-Location }
    }
    'run' {
        Need-Venv
        $env:DEMO_MODE = '1'; $env:DEV_LOGIN = '1'
        Write-Host "Starting $Url  (Ctrl+C to stop). Opening My Watch as the demo patient..." -ForegroundColor Green
        Start-Job -ScriptBlock { param($u) Start-Sleep 4; Start-Process "$u/wearable/dev-login/patient" } -ArgumentList $Url | Out-Null
        Push-Location $Backend; try { & $Py -m flask --app app run --debug --port $Port } finally { Pop-Location }
    }
    'sim' {
        Need-Venv
        $env:DEMO_MODE = '1'
        if ($Patient -gt 0) { $who = @('--patient', "$Patient") } else { $who = @('--demo-patient') }
        Push-Location $Backend; try { & $Py -m wearable.simulator @who --scenario $Scenario } finally { Pop-Location }
    }
    'send' {
        Need-Venv
        if (-not $Token) { throw 'Pass -Token <device token> (create one on the My Watch page).' }
        Push-Location $Backend; try { & $Py -m wearable.devtool send --url $Url --token $Token --hr $Hr } finally { Pop-Location }
    }
    'tunnel' {
        if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
            throw 'cloudflared is not installed. Install it with:  winget install --id Cloudflare.cloudflared   (then open a new terminal)'
        }
        Write-Host 'Look for the https://....trycloudflare.com URL below. Use it as the ingest URL in the iPhone Shortcut.' -ForegroundColor Green
        cloudflared tunnel --url "http://127.0.0.1:$Port"
    }
    'status' {
        Need-Venv
        Push-Location $Backend; try { & $Py -m wearable.devtool status } finally { Pop-Location }
    }
    'reset-db' {
        Need-Venv
        Push-Location $Backend; try { & $Py -m wearable.devtool reset-db } finally { Pop-Location }
    }
    default {
        $lines = Get-Content $PSCommandPath
        $end = [Array]::IndexOf($lines, '#>')
        ($lines[1..($end - 1)]) -join "`n" | Write-Host
    }
}
