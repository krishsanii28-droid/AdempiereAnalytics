<#
Tests the embedded InsightAI window without a person at the screen.

  powershell -ExecutionPolicy Bypass -File scripts\test_form.ps1

For each test login it opens the form through ADempiere's own FormFrame (off-screen), waits for
the dashboard to load inside it, reads who is signed in and which organisations are offered, and
saves a picture of the window to build\form_<login>.png. Needs the InsightAI service running and
a desktop session (JavaFX cannot start without one).
#>
param([string]$AdempiereHome = $(if ($env:ADEMPIERE_HOME) { $env:ADEMPIERE_HOME } else { 'C:\Adempiere' }))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$javaHome = $env:JAVA_HOME
$lib = Join-Path $AdempiereHome 'lib'
# javaws.jar: ADempiere's client start-up refers to Java Web Start classes when it is not headless
$cp = "$lib\insightai.jar;$lib\Adempiere.jar;$lib\AdempiereCLib.jar;$lib\CompiereJasperReqs.jar;$javaHome\jre\lib\javaws.jar"
$out = Join-Path $root 'build\harness'
New-Item -ItemType Directory -Force $out | Out-Null
& "$javaHome\bin\javac.exe" -nowarn -encoding UTF-8 -cp $cp -d $out (Join-Path $root 'tests\java\FormHarness.java')
if ($LASTEXITCODE -ne 0) { throw 'javac failed for the form harness.' }

$cases = @(
    @{ Name = 'GardenAdmin as GardenWorld Admin';     Tag = 'admin';      User = 101; Role = 102;     Org = 11;    Expect = 'open';    Orgs = 8 },
    @{ Name = 'test_salerep as SalesRep(Restricted)'; Tag = 'restricted'; User = 104; Role = 1000000; Org = 50001; Expect = 'open';    Orgs = 1 },
    @{ Name = 'GardenUser as GardenWorld User (role not granted)'; Tag = 'ungranted'; User = 102; Role = 103; Org = 11; Expect = 'refused'; Orgs = 0 }
)
$failed = 0
foreach ($case in $cases) {
    Write-Host "`n== $($case.Name)"
    $picture = Join-Path $root "build\form_$($case.Tag).png"
    if (Test-Path $picture) { Remove-Item $picture -Confirm:$false }
    $ErrorActionPreference = 'Continue'
    $text = (& "$javaHome\bin\java.exe" -Xmx512m "-DADEMPIERE_HOME=$AdempiereHome" "-DPropertyFile=$AdempiereHome\Adempiere.properties" `
        -cp "$out;$cp" FormHarness $case.User $case.Role 11 $case.Org $picture 2>&1 | ForEach-Object { "$_" }) -join "`n"
    $ErrorActionPreference = 'Stop'
    if ($text -notmatch '(FORM opened=[^\r\n]*)') { Write-Host '   FAIL: no result'; ($text -split "`n") | Select-Object -Last 8 | ForEach-Object { "   $_" }; $failed++; continue }
    $line = $Matches[1]
    $inMenu = if ($text -match 'MENU embedded=(\w+) browser=(\w+)') { "$($Matches[1]),$($Matches[2])" } else { 'unknown' }
    if ($case.Expect -eq 'refused') {
        # Two separate protections. ADempiere leaves the entries out of this role's menu. And if the
        # window is opened anyway, as this test does, the service refuses to sign the role in.
        if ($inMenu -eq 'false,false') { Write-Host "   ok: neither InsightAI entry is in this role's menu" }
        else { Write-Host "   FAIL: menu entries shown (embedded,browser) = $inMenu"; $failed++ }
        $status = if ($text -match 'STATUS ([^\r\n]*)') { $Matches[1] } else { '' }
        if ($line -match 'loaded=false' -and $status -match 'not been granted access') { Write-Host "   ok: forced open, the window shows no data and says: $status" }
        else { Write-Host "   FAIL: $line $status"; $failed++ }
        continue
    }
    if ($inMenu -eq 'true,true') { Write-Host "   ok: both InsightAI entries are in this role's menu" }
    else { Write-Host "   FAIL: menu entries shown (embedded,browser) = $inMenu"; $failed++; continue }
    if ($line -notmatch 'opened=true loaded=true seen=(\{.*\})') { Write-Host "   FAIL: $line"; $failed++; continue }
    $seen = $Matches[1] | ConvertFrom-Json
    $orgs = @($seen.organisations | Select-Object -Skip 1)     # the first option is "All my organisations" / "My organisation"
    Write-Host "   signed in as: $($seen.who)"
    Write-Host "   organisations offered: $($orgs -join ', ')"
    Write-Host "   KPI cards: $($seen.kpiCards), charts drawn: $($seen.charts), page: $($seen.path)"
    $ok = ($orgs.Count -eq $case.Orgs) -and ($seen.kpiCards -ge 8) -and ($seen.charts -ge 1) -and $seen.embedded -and (-not $seen.signOutShown) -and (Test-Path $picture)
    if ($ok) { Write-Host "   ok: dashboard shown inside the ADempiere window; picture saved to $picture" } else { Write-Host '   FAIL: the window did not show what was expected'; $failed++ }
}
Write-Host "`n$(if ($failed) { "$failed check(s) FAILED" } else { 'All embedded-window checks passed' })"
exit $failed
