<#
Creates the Python environment for the analytics service and its signing key.

  powershell -ExecutionPolicy Bypass -File scripts\setup_service.ps1          # runtime packages
  powershell -ExecutionPolicy Bypass -File scripts\setup_service.ps1 -Dev     # plus test packages

Uses Python 3.12 through the py launcher and installs into .venv inside this project only.
No other Python installation on the machine is touched.
#>
param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $python)) {
    py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment. Is Python 3.12 installed?' }
}
$requirements = if ($Dev) { 'requirements-dev.txt' } else { 'requirements.txt' }
& $python -m pip install --quiet --disable-pip-version-check -r (Join-Path $root $requirements)
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

# Signing key for session tokens: generated once, kept in .env.
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) { throw '.env not found. Run scripts\db_install.ps1 first.' }
if (-not (Select-String -Path $envFile -Pattern '^INSIGHTAI_SECRET_KEY=' -Quiet)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $key = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    [System.IO.File]::AppendAllText($envFile, "INSIGHTAI_SECRET_KEY=$key`r`n")
    Write-Host 'Added INSIGHTAI_SECRET_KEY to .env'
}
Write-Host "Environment ready: $venv"
