<#
End-to-end test of the ADempiere -> InsightAI hand-off without the desktop GUI.

  powershell -ExecutionPolicy Bypass -File scripts\test_launcher.ps1

For each test login it runs the real launcher process inside a headless ADempiere environment
(tests\java\LauncherHarness.java), then follows the launch link the way a browser would and
checks what the resulting session can see. Needs the InsightAI service to be running.
Each run adds process-instance rows to ADempiere (AD_PInstance), as running any process does.
#>
param([string]$AdempiereHome = $(if ($env:ADEMPIERE_HOME) { $env:ADEMPIERE_HOME } else { 'C:\Adempiere' }))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$javaHome = $env:JAVA_HOME
$lib = Join-Path $AdempiereHome 'lib'
$cp = "$lib\insightai.jar;$lib\Adempiere.jar;$lib\AdempiereCLib.jar"
$out = Join-Path $root 'build\harness'
New-Item -ItemType Directory -Force $out | Out-Null
& "$javaHome\bin\javac.exe" -nowarn -encoding UTF-8 -cp $cp -d $out (Join-Path $root 'tests\java\LauncherHarness.java')
if ($LASTEXITCODE -ne 0) { throw 'javac failed for the harness.' }

# user, role, client, org, what should happen
$cases = @(
    @{ Name = 'GardenAdmin as GardenWorld Admin';       User = 101; Role = 102;     Org = 11;    Expect = 'open' },
    @{ Name = 'test_salerep as SalesRep(Restricted)';   User = 104; Role = 1000000; Org = 50001; Expect = 'open' },
    @{ Name = 'GardenUser as GardenWorld User (role not granted)'; User = 102; Role = 103; Org = 11; Expect = 'refused' },
    @{ Name = 'test_salerep claiming GardenWorld Admin (role not held)'; User = 104; Role = 102; Org = 11; Expect = 'refused' }
)
$failed = 0
foreach ($case in $cases) {
    Write-Host "`n== $($case.Name)"
    $ErrorActionPreference = 'Continue'
    $lines = & "$javaHome\bin\java.exe" -Xmx256m "-DADEMPIERE_HOME=$AdempiereHome" "-DPropertyFile=$AdempiereHome\Adempiere.properties" `
        '-Dinsightai.nobrowser=true' '-Djava.awt.headless=true' -cp "$out;$cp" LauncherHarness $case.User $case.Role 11 $case.Org 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = 'Stop'
    $text = $lines -join "`n"
    if ($text -match 'IllegalAccessError: (Cannot access Process[^\r\n]*)') {
        # ADempiere checks AD_Process_Access itself before the launcher runs
        if ($case.Expect -eq 'refused') { Write-Host "   ok: ADempiere refused to start the process ($($Matches[1]))" }
        else { Write-Host "   FAIL: ADempiere refused to start the process ($($Matches[1]))"; $failed++ }
        continue
    }
    $result = if ($text -match '(HARNESS error=[^\r\n]*)') { $Matches[1] } else { $null }
    if (-not $result) { Write-Host '   FAIL: the harness produced no result'; $lines | Select-Object -Last 8 | ForEach-Object { "   $_" }; $failed++; continue }
    $url = if ($result -match '(http://\S+/launch\?code=\S+)') { $Matches[1] } else { $null }
    Write-Host ('   process result: ' + ($result -replace 'code=\S+', 'code=<one-time code>'))

    if ($case.Expect -eq 'refused') {
        if ($url) { Write-Host '   FAIL: a launch link was issued'; $failed++ } else { Write-Host '   ok: no launch link issued' }
        continue
    }
    if (-not $url) { Write-Host '   FAIL: no launch link'; $failed++; continue }

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $me = Invoke-RestMethod -Uri $url -WebSession $session -MaximumRedirection 5 | Out-Null
    $base = $url -replace '/launch\?.*$', ''
    $me = Invoke-RestMethod -Uri "$base/api/me" -WebSession $session
    $orgs = ($me.filters.orgs | ForEach-Object { $_.name }) -join ', '
    Write-Host "   ok: session is $($me.user) / $($me.role), organisations: $orgs"
    try { Invoke-WebRequest -Uri $url -UseBasicParsing -MaximumRedirection 0 | Out-Null; Write-Host '   FAIL: the launch link worked a second time'; $failed++ }
    catch { if ($_.Exception.Response.StatusCode.value__ -eq 401) { Write-Host '   ok: the launch link cannot be reused (401)' } else { Write-Host "   FAIL: unexpected $($_.Exception.Message)"; $failed++ } }
}
Write-Host "`n== InsightAI service not running (launcher pointed at a closed port)"
$ErrorActionPreference = 'Continue'
$down = (& "$javaHome\bin\java.exe" -cp "$out;$cp" LauncherHarness unreachable 'http://127.0.0.1:9' 2>&1 | ForEach-Object { "$_" }) -join "`n"
$ErrorActionPreference = 'Stop'
if ($down -match 'HARNESS error=true summary=AdempiereUserError: (The InsightAI service is not running[^\r\n]*)') { Write-Host "   ok: ADempiere shows: $($Matches[1])" }
else { Write-Host "   FAIL: $down"; $failed++ }

Write-Host "`n$(if ($failed) { "$failed check(s) FAILED" } else { 'All launcher checks passed' })"
exit $failed
