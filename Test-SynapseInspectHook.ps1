$ErrorActionPreference = "Stop"

$Port = 9229

try {
    $targets = Invoke-RestMethod "http://127.0.0.1:$Port/json/list" -TimeoutSec 2
}
catch {
    Write-Host "FAIL: Nothing is listening on 127.0.0.1:$Port"
    Write-Host "Fully exit Synapse and reopen it normally, then run this test again."
    exit 1
}

if (-not $targets) {
    Write-Host "FAIL: Inspector endpoint responded but returned no targets."
    exit 2
}

$target = @($targets)[0]

Write-Host "PASS: Synapse Node inspector is available."
Write-Host ""
Write-Host "Title: $($target.title)"
Write-Host "Type:  $($target.type)"
Write-Host "URL:   $($target.url)"
Write-Host "WS:    $($target.webSocketDebuggerUrl)"
