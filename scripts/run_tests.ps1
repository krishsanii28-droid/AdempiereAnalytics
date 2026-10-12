<#
Runs every InsightAI check and prints one summary.

  powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
  powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1 -SkipLauncher    # no JDK / ADempiere integration not installed

  1. Python tests (pytest): KPI logic, views, API, access rules, forecasting, assistant, launch hand-off
  2. Read-only role smoke test (db\verify_ro.sql)
  3. Cross-check of the views against ADempiere's own figures (db\crosscheck.sql)
  4. ADempiere launcher, end to end, without the GUI (needs the service running)

Nothing here changes ADempiere business data. Step 4 adds process-instance rows, as running any process does.
#>
param([switch]$SkipLauncher)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$results = [ordered]@{}

Write-Host "`n===== 1. Python tests ====="
& (Join-Path $root '.venv\Scripts\python.exe') -m pytest -q 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch 'Warning|testclient|^\s*$|docs\.pytest' } | Select-Object -Last 6
$results['Python tests'] = $LASTEXITCODE

Write-Host "`n===== 2. Read-only role smoke test ====="
$smoke = powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\db_verify.ps1') 2>&1 | ForEach-Object { "$_" }
$refused = ($smoke | Where-Object { $_ -match 'ERROR:' }).Count
$viewLines = ($smoke | Where-Object { $_ -match '^\s*v_\w+\s*\|\s*\d+' }).Count
Write-Host "$viewLines views readable; $refused forbidden statements refused"
$leaked = ($smoke | Where-Object { $_ -match '^(CREATE TABLE|INSERT|UPDATE|DELETE)\b' }).Count
$results['Read-only role'] = if ($viewLines -ge 16 -and $refused -ge 8 -and $leaked -eq 0) { 0 } else { 1 }

Write-Host "`n===== 3. Cross-check against ADempiere ====="
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\db_crosscheck.ps1') 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match 'FAIL|ERROR|passed' }
$results['Cross-check'] = $LASTEXITCODE

if (-not $SkipLauncher) {
    Write-Host "`n===== 4. ADempiere launcher ====="
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\test_launcher.ps1') 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match '^==|^\s+(ok|FAIL)|passed|FAILED' }
    $results['ADempiere launcher'] = $LASTEXITCODE
}

Write-Host "`n===== Summary ====="
$failed = 0
foreach ($name in $results.Keys) {
    $ok = $results[$name] -eq 0
    if (-not $ok) { $failed++ }
    Write-Host ("{0,-20} {1}" -f $name, $(if ($ok) { 'PASS' } else { 'FAIL' }))
}
exit $failed
