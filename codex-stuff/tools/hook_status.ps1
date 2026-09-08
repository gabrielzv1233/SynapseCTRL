$ErrorActionPreference = "SilentlyContinue"

$Port = 9229
$StableExe = Join-Path $env:ProgramFiles "Razer\RazerAppEngine\RazerAppEngine.exe"
$IFEOBase = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\RazerAppEngine.exe"
$FilterKey = Join-Path $IFEOBase "SynapseCTRL"

$result = [ordered]@{
    stableLauncherExists = Test-Path $StableExe
    ifeoBaseExists = Test-Path $IFEOBase
    filterExists = Test-Path $FilterKey
    useFilter = $null
    filterFullPath = $null
    debugger = $null
    inspectorReachable = $false
    inspectorTarget = $null
}

if (Test-Path $IFEOBase) {
    $result.useFilter = (Get-ItemProperty $IFEOBase -Name UseFilter).UseFilter
}
if (Test-Path $FilterKey) {
    $props = Get-ItemProperty $FilterKey
    $result.filterFullPath = $props.FilterFullPath
    $result.debugger = $props.Debugger
}

try {
    $targets = Invoke-RestMethod "http://127.0.0.1:$Port/json/list" -TimeoutSec 2
    if ($targets) {
        $result.inspectorReachable = $true
        $result.inspectorTarget = @($targets)[0]
    }
} catch {}

$result | ConvertTo-Json -Depth 8
