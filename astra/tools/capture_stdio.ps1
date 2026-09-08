param(
    [string]$OutputDirectory = "$PSScriptRoot\..\diagnostics\stdio",
    [int]$Port = 9229,
    [switch]$NoKill
)

$ErrorActionPreference = "Stop"
$Root = Join-Path $env:ProgramFiles "Razer\RazerAppEngine"
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$exe = Get-ChildItem -Path $Root -Directory -Filter "app-*" |
    Sort-Object {
        try { [version]($_.Name -replace '^app-', '') }
        catch { [version]'0.0.0' }
    } -Descending |
    ForEach-Object { Join-Path $_.FullName "RazerAppEngine.exe" } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

if (-not $exe) { throw "Versioned RazerAppEngine.exe not found under $Root" }

if (-not $NoKill) {
    Get-Process RazerAppEngine -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 750
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdout = Join-Path $OutputDirectory "$stamp-stdout.log"
$stderr = Join-Path $OutputDirectory "$stamp-stderr.log"

Start-Process `
    -FilePath $exe `
    -ArgumentList @("--inspect=127.0.0.1:$Port", "--url-params=apps=synapse") `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr

[ordered]@{
    executable = $exe
    inspector = "127.0.0.1:$Port"
    stdout = $stdout
    stderr = $stderr
} | ConvertTo-Json
