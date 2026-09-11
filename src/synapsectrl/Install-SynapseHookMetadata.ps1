param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$HookVersion,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$HookProtocolVersion,

    [Parameter(Mandatory = $true)]
    [string]$SynapseCtrlVersion,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedFingerprint,

    [switch]$Uninstall,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$IFEOBase = (
    "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\" +
    "Image File Execution Options\RazerAppEngine.exe"
)
$FilterKey = Join-Path $IFEOBase "SynapseCTRL"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-SystemPowerShell {
    $path = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        $path = Join-Path $env:SystemRoot "Sysnative\WindowsPowerShell\v1.0\powershell.exe"
    }
    return $path
}

function Remove-SynapseCtrlMetadata {
    if (-not (Test-Path -LiteralPath $FilterKey)) {
        return
    }

    foreach ($valueName in @(
        'HookProtocolVersion',
        'HookFingerprint',
        'InstalledByVersion',
        'InstalledAtUtc'
    )) {
        Remove-ItemProperty -LiteralPath $FilterKey -Name $valueName -ErrorAction SilentlyContinue
    }

    $remaining = Get-Item -LiteralPath $FilterKey
    if ($remaining.ValueCount -eq 0 -and $remaining.SubKeyCount -eq 0) {
        Remove-Item -LiteralPath $FilterKey -Force
    }
}

if (-not (Test-IsAdministrator)) {
    $elevatedArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-InstallerPath", "`"$InstallerPath`"",
        "-HookVersion", "$HookVersion",
        "-HookProtocolVersion", "$HookProtocolVersion",
        "-SynapseCtrlVersion", "$SynapseCtrlVersion",
        "-ExpectedFingerprint", "$ExpectedFingerprint",
        "-NoPause"
    )
    if ($Uninstall) {
        $elevatedArgs += "-Uninstall"
    }

    try {
        $child = Start-Process -FilePath (Get-SystemPowerShell) -Verb RunAs `
            -WindowStyle Hidden -ArgumentList $elevatedArgs -Wait -PassThru
        $resultCode = $child.ExitCode
        if ($resultCode -ne 0) {
            Write-Error "Elevated SynapseCTRL hook operation failed (exit $resultCode)." -ErrorAction Continue
        }
    } catch {
        Write-Error "Could not complete elevated SynapseCTRL hook operation: $_" -ErrorAction Continue
        $resultCode = 1
    }

    if (-not $NoPause) { Read-Host "Press Enter to continue..." | Out-Null }
    exit $resultCode
}

try {
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw "Packaged Synapse hook installer not found: $InstallerPath"
    }

    $actualFingerprint = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualFingerprint -ne $ExpectedFingerprint.ToLowerInvariant()) {
        throw "Packaged hook fingerprint mismatch. Reinstall SynapseCTRL before modifying the launch hook."
    }

    $legacyArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$InstallerPath`"",
        "-NoPause"
    )
    if ($Uninstall) {
        $legacyArgs += "-Uninstall"
    }

    $legacy = Start-Process -FilePath (Get-SystemPowerShell) -WindowStyle Hidden `
        -ArgumentList $legacyArgs -Wait -PassThru
    if ($legacy.ExitCode -ne 0) {
        throw "Native Synapse hook installer failed (exit $($legacy.ExitCode))."
    }

    if ($Uninstall) {
        Remove-SynapseCtrlMetadata
        Write-Host "SynapseCTRL hook metadata removed."
    } else {
        if (-not (Test-Path -LiteralPath $FilterKey)) {
            throw "The native hook installer completed but the SynapseCTRL IFEO filter was not created."
        }

        New-ItemProperty -LiteralPath $FilterKey -Name HookVersion -PropertyType DWord `
            -Value $HookVersion -Force | Out-Null
        New-ItemProperty -LiteralPath $FilterKey -Name HookProtocolVersion -PropertyType DWord `
            -Value $HookProtocolVersion -Force | Out-Null
        New-ItemProperty -LiteralPath $FilterKey -Name HookFingerprint -PropertyType String `
            -Value $actualFingerprint -Force | Out-Null
        New-ItemProperty -LiteralPath $FilterKey -Name InstalledByVersion -PropertyType String `
            -Value $SynapseCtrlVersion -Force | Out-Null
        New-ItemProperty -LiteralPath $FilterKey -Name InstalledAtUtc -PropertyType String `
            -Value ([DateTime]::UtcNow.ToString("O")) -Force | Out-Null

        Write-Host "SynapseCTRL hook metadata: v$HookVersion / protocol v$HookProtocolVersion / $($actualFingerprint.Substring(0, 12))"
        Write-Host "Installed by SynapseCTRL $SynapseCtrlVersion"
    }

    $resultCode = 0
} catch {
    Write-Error "SynapseCTRL hook metadata operation failed: $_" -ErrorAction Continue
    $resultCode = 1
}

if (-not $NoPause) { Read-Host "Press Enter to continue..." | Out-Null }
exit $resultCode
