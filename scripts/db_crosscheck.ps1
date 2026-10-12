<#
Compares the insightai views with ADempiere's own figures (Performance measures, RV_OpenItem,
M_Storage, raw document tables). Every line should say PASS.

  powershell -ExecutionPolicy Bypass -File scripts\db_crosscheck.ps1
  powershell -ExecutionPolicy Bypass -File scripts\db_crosscheck.ps1 -ClientId 11

Connects as the adempiere role, because the comparison needs ADempiere's tables, in a session
forced read-only. Exit code is the number of failed checks.
#>
param(
    [int]$ClientId = 11,
    [string]$AdempiereHome = $(if ($env:ADEMPIERE_HOME) { $env:ADEMPIERE_HOME } else { 'C:\Adempiere' }),
    [string]$Psql = 'C:\Program Files\PostgreSQL\14\bin\psql.exe'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$props = @{}
Get-Content (Join-Path $AdempiereHome 'AdempiereEnv.properties') | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $props[$k] = $v
}
$env:PGPASSWORD = $props['ADEMPIERE_DB_PASSWORD']
$env:PGOPTIONS = '-c default_transaction_read_only=on -c statement_timeout=60000'
$env:PGCLIENTENCODING = 'UTF8'
$ErrorActionPreference = 'Continue'
try {
    $lines = & $Psql -X -q -h $props['ADEMPIERE_DB_SERVER'] -p $props['ADEMPIERE_DB_PORT'] -U $props['ADEMPIERE_DB_USER'] -d $props['ADEMPIERE_DB_NAME'] `
        -P pager=off -v "client=$ClientId" -f (Join-Path $root 'db\crosscheck.sql') 2>&1 | ForEach-Object { "$_" }
} finally {
    $env:PGPASSWORD = $null
    $env:PGOPTIONS = $null
}
$lines | Where-Object { $_ -notmatch '^\s*$' }
$passed = ($lines | Where-Object { $_ -match '^\s*PASS\b' }).Count
$failed = ($lines | Where-Object { $_ -match '^\s*FAIL\b|ERROR' }).Count
if ($passed -eq 0) { $failed++ }
Write-Host "$passed passed, $failed failed"
exit $failed
