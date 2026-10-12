<#
Starts the InsightAI service. Host and port come from config.toml.

  powershell -ExecutionPolicy Bypass -File scripts\run_service.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'No .venv found. Run scripts\setup_service.ps1 first.' }
Set-Location $root
& $python -m insightai
