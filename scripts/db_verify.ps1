<#
Runs a SQL file as the read-only service role, using the connection in .env.

  powershell -ExecutionPolicy Bypass -File scripts\db_verify.ps1                    # db\verify_ro.sql
  powershell -ExecutionPolicy Bypass -File scripts\db_verify.ps1 -SqlFile my.sql
#>
param(
    [string]$SqlFile,
    [string]$Psql = 'C:\Program Files\PostgreSQL\14\bin\psql.exe'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $SqlFile) { $SqlFile = Join-Path $root 'db\verify_ro.sql' }

$cfg = @{}
Get-Content (Join-Path $root '.env') | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $cfg[$k] = $v
}
$env:PGPASSWORD = $cfg['INSIGHTAI_DB_PASSWORD']
$env:PGCLIENTENCODING = 'UTF8'
$ErrorActionPreference = 'Continue'   # psql reports refused statements on stderr; that is expected output here
try {
    & $Psql -X -h $cfg['INSIGHTAI_DB_HOST'] -p $cfg['INSIGHTAI_DB_PORT'] -U $cfg['INSIGHTAI_DB_USER'] -d $cfg['INSIGHTAI_DB_NAME'] -P pager=off -f $SqlFile 2>&1 | ForEach-Object { "$_" }
} finally {
    $env:PGPASSWORD = $null
}
