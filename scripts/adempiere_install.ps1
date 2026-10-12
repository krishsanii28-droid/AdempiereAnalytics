<#
Installs (or removes) the InsightAI menu entry in ADempiere.

  powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1 -Roles 'GardenWorld Admin','GardenWorld User'
  powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1 -Uninstall

What it does:
  1. Compiles adempiere\src into build\insightai.jar (Java 8, against ADempiere's own Adempiere.jar).
  2. Copies three NEW files into the ADempiere installation. No existing file is modified:
       lib\insightai.jar                  the launcher process
       RUN_Adempiere_InsightAI.bat        starts the desktop client with that jar on the classpath
       insightai-launcher.properties      service address and the shared launch key
  3. Adds the dictionary records (entity type INSAI, process, menu entry under Performance Analysis)
     and grants the process to the roles in -Roles only.
  4. Refreshes the insightai database views (the service checks role access through one of them).

Close and reopen the ADempiere client afterwards, using RUN_Adempiere_InsightAI.bat.
#>
param(
    [string]$AdempiereHome = $(if ($env:ADEMPIERE_HOME) { $env:ADEMPIERE_HOME } else { 'C:\Adempiere' }),
    [string[]]$Roles = @('GardenWorld Admin', 'SalesRep(Restricted)'),
    [string]$Psql = 'C:\Program Files\PostgreSQL\14\bin\psql.exe',
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$installed = @('lib\insightai.jar', 'RUN_Adempiere_InsightAI.bat', 'insightai-launcher.properties') | ForEach-Object { Join-Path $AdempiereHome $_ }

$props = @{}
Get-Content (Join-Path $AdempiereHome 'AdempiereEnv.properties') | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $props[$k] = $v -replace '\\(.)', '$1'      # .properties escapes ':' and '\'
}

function Invoke-Psql([string[]]$PsqlArgs) {
    $env:PGPASSWORD = $props['ADEMPIERE_DB_PASSWORD']
    $env:PGCLIENTENCODING = 'UTF8'
    try {
        & $Psql -X -q -h $props['ADEMPIERE_DB_SERVER'] -p $props['ADEMPIERE_DB_PORT'] -U $props['ADEMPIERE_DB_USER'] -d $props['ADEMPIERE_DB_NAME'] -P pager=off -v ON_ERROR_STOP=1 @PsqlArgs
        if ($LASTEXITCODE -ne 0) { throw "psql failed (exit $LASTEXITCODE)" }
    } finally {
        $env:PGPASSWORD = $null
    }
}

if ($Uninstall) {
    Invoke-Psql @('-1', '-f', (Join-Path $root 'adempiere\dictionary_uninstall.sql'))
    foreach ($file in $installed) { if (Test-Path $file) { Remove-Item $file -Confirm:$false; Write-Host "Removed $file" } }
    Write-Host 'InsightAI menu entry removed from ADempiere. Restart the ADempiere client.'
    return
}

# --- 1. compile ---------------------------------------------------------------------------
$javaHome = if ($env:JAVA_HOME) { $env:JAVA_HOME } else { $props['JAVA_HOME'] }
$javac = Join-Path $javaHome 'bin\javac.exe'
$jar = Join-Path $javaHome 'bin\jar.exe'
if (-not (Test-Path $javac)) { throw "javac not found under $javaHome. A JDK (not a JRE) is needed." }
$build = Join-Path $root 'build'
$classes = Join-Path $build 'classes'
if (Test-Path $classes) { Remove-Item $classes -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force $classes | Out-Null
$sources = Get-ChildItem (Join-Path $root 'adempiere\src') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& $javac -source 1.8 -target 1.8 -encoding UTF-8 -nowarn -cp (Join-Path $AdempiereHome 'lib\Adempiere.jar') -d $classes $sources
if ($LASTEXITCODE -ne 0) { throw 'javac failed.' }
$manifest = Join-Path $build 'MANIFEST.MF'
[System.IO.File]::WriteAllText($manifest, "Manifest-Version: 1.0`r`nImplementation-Title: ADempiere InsightAI launcher`r`nImplementation-Version: 1.0`r`n")
$jarFile = Join-Path $build 'insightai.jar'
& $jar cfm $jarFile $manifest -C $classes .
if ($LASTEXITCODE -ne 0) { throw 'jar failed.' }

# --- 2. files into ADEMPIERE_HOME (new files only) ------------------------------------------
if (-not (Test-Path $envFile)) { throw '.env not found. Run scripts\db_install.ps1 and scripts\setup_service.ps1 first.' }
$launchKey = (Get-Content $envFile | Where-Object { $_ -match '^INSIGHTAI_LAUNCH_KEY=' } | Select-Object -First 1) -replace '^INSIGHTAI_LAUNCH_KEY=', ''
if (-not $launchKey) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $launchKey = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    [System.IO.File]::AppendAllText($envFile, "INSIGHTAI_LAUNCH_KEY=$launchKey`r`n")
    Write-Host 'Added INSIGHTAI_LAUNCH_KEY to .env (restart the InsightAI service so it reads it)'
}
$config = Get-Content (Join-Path $root 'config.toml') -Raw
$publicUrl = if ($config -match '(?m)^public_url\s*=\s*"([^"]+)"') { $Matches[1] } else {
    $hostName = if ($config -match '(?m)^host\s*=\s*"([^"]+)"') { $Matches[1] } else { '127.0.0.1' }
    $port = if ($config -match '(?m)^port\s*=\s*(\d+)') { $Matches[1] } else { '8765' }
    "http://${hostName}:$port"
}
Copy-Item $jarFile $installed[0] -Force
Copy-Item (Join-Path $root 'adempiere\RUN_Adempiere_InsightAI.bat') $installed[1] -Force
[System.IO.File]::WriteAllLines($installed[2], @(
    '# InsightAI launcher settings. Written by scripts\adempiere_install.ps1.',
    '# The key lets this ADempiere installation open InsightAI sessions: keep this file readable only by ADempiere users.',
    "url=$publicUrl",
    "key=$launchKey"))
foreach ($file in $installed) { Write-Host "Installed $file" }

# --- 3 and 4. database -----------------------------------------------------------------------
Invoke-Psql @('-1', '-f', (Join-Path $root 'db\01_install.sql'))
$roleList = ($Roles | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ','
Invoke-Psql @('-1', '-v', "roles=$roleList", '-f', (Join-Path $root 'adempiere\dictionary_install.sql'))
Write-Host "Done. Restart the InsightAI service, then open ADempiere with RUN_Adempiere_InsightAI.bat."
