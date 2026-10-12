<#
Starts the real ADempiere desktop client with InsightAI and checks the option on the Performance tab.

  powershell -ExecutionPolicy Bypass -File scripts\test_client.ps1

It logs in automatically as the user saved in ADempiere's login settings, using a temporary copy
of Adempiere.properties with AutoLogin switched on (your own file is not changed). An ADempiere
main window and an InsightAI window appear on screen for about half a minute and close by themselves.
The picture of the main window is saved to build\client_main.png.
Needs the InsightAI service running and a saved ADempiere password (Login > "Store Password").
#>
param([string]$AdempiereHome = $(if ($env:ADEMPIERE_HOME) { $env:ADEMPIERE_HOME } else { 'C:\Adempiere' }))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$javaHome = $env:JAVA_HOME
$lib = Join-Path $AdempiereHome 'lib'
$cp = "$lib\insightai.jar;$lib\Adempiere.jar;$lib\AdempiereCLib.jar;$lib\CompiereJasperReqs.jar"
$out = Join-Path $root 'build\harness'
New-Item -ItemType Directory -Force $out | Out-Null
& "$javaHome\bin\javac.exe" -nowarn -encoding UTF-8 -cp $cp -d $out (Join-Path $root 'tests\java\ClientHarness.java')
if ($LASTEXITCODE -ne 0) { throw 'javac failed for the client harness.' }

# ADempiere stores plain property values with an "xyz" prefix
$props = Join-Path $root 'build\Adempiere.autologin.properties'
(Get-Content (Join-Path $AdempiereHome 'Adempiere.properties')) -replace '^AutoLogin=.*', 'AutoLogin=xyzY' | Set-Content $props -Encoding ascii
$picture = Join-Path $root 'build\client_main.png'
if (Test-Path $picture) { Remove-Item $picture -Confirm:$false }

$ErrorActionPreference = 'Continue'
$text = (& "$javaHome\bin\java.exe" -Xmx512m "-DADEMPIERE_HOME=$AdempiereHome" "-DPropertyFile=$props" `
    -cp "$out;$cp" ClientHarness $picture open 2>&1 | ForEach-Object { "$_" }) -join "`n"
$ErrorActionPreference = 'Stop'
Remove-Item $props -Confirm:$false

$failed = 0
($text -split "`n") | Where-Object { $_ -match '^LOGIN ' } | ForEach-Object { Write-Host $_ }
if ($text -match '(CLIENT mainWindow=true[^\r\n]*)') {
    $line = $Matches[1]
    Write-Host "main window: $line"
    if ($line -match 'optionOnTab=Performance' -and $line -match 'buttonVisible=true') { Write-Host 'ok: the InsightAI option is on the Performance tab and visible when ADempiere opens' }
    else { Write-Host 'FAIL: the option is not visible on the Performance tab'; $failed++ }
} else {
    Write-Host 'FAIL: the ADempiere main window did not open (is a password saved for automatic login?)'
    ($text -split "`n") | Where-Object { $_ -match 'CLIENT|Exception|Error' } | Select-Object -First 6
    $failed++
}
if ($text -match '(WINDOW opened=[^\r\n]*)') {
    $line = $Matches[1]
    Write-Host "after pressing Open: $line"
    if ($line -match 'opened=true loaded=true' -and $line -match '"kpiCards":8') { Write-Host 'ok: the dashboard opened in an ADempiere window, signed in' }
    else { Write-Host 'FAIL: the dashboard did not load'; $failed++ }
} elseif ($failed -eq 0) { Write-Host 'FAIL: pressing Open gave no result'; $failed++ }
Write-Host "$(if ($failed) { "$failed check(s) FAILED" } else { 'All desktop-client checks passed' })"
exit $failed
