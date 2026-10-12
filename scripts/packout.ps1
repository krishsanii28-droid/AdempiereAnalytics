<#
Exports the InsightAI dictionary records as a 2Pack into adempiere\2pack, using ADempiere's own PackOut process.

  powershell -ExecutionPolicy Bypass -File scripts\packout.ps1

Run it after scripts\adempiere_install.ps1 whenever the dictionary records change.
The package holds the entity type, the launcher process and the menu entry with its place in the
menu tree. 2Pack does not carry process access: grant roles with adempiere_install.ps1 -Roles or in
the Role window after importing.
#>
param([string]$AdempiereHome = $(if ($env:ADEMPIERE_HOME) { $env:ADEMPIERE_HOME } else { 'C:\Adempiere' }))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lib = Join-Path $AdempiereHome 'lib'
$cp = "$lib\Adempiere.jar;$lib\AdempiereCLib.jar"
$out = Join-Path $root 'build\harness'
$dir = (Join-Path $root 'build\2pack') + '\'
New-Item -ItemType Directory -Force $out, $dir | Out-Null
& "$env:JAVA_HOME\bin\javac.exe" -nowarn -encoding UTF-8 -cp $cp -d $out (Join-Path $root 'tests\java\PackOutHarness.java')
if ($LASTEXITCODE -ne 0) { throw 'javac failed.' }
$ErrorActionPreference = 'Continue'
$lines = & "$env:JAVA_HOME\bin\java.exe" -Xmx384m "-DADEMPIERE_HOME=$AdempiereHome" "-DPropertyFile=$AdempiereHome\Adempiere.properties" `
    '-Djava.awt.headless=true' -cp "$out;$cp" PackOutHarness $dir 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = 'Stop'
$result = ($lines -join "`n")
if ($result -notmatch 'PACKOUT error=false') { $lines | Select-Object -Last 15; throw 'PackOut did not finish.' }
$target = Join-Path $root 'adempiere\2pack'
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item (Join-Path $dir 'InsightAI.zip') $target -Force
Copy-Item (Join-Path $dir 'InsightAI\dict\PackOut.xml') $target -Force
Write-Host "2Pack written to $target (InsightAI.zip for PackIn, PackOut.xml for reading)"
