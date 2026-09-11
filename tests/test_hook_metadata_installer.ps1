# Offline validation for the metadata-aware hook installer. This test only parses
# and inspects the script; it never elevates, changes IFEO, or launches Synapse.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $projectRoot 'src\synapsectrl\Install-SynapseHookMetadata.ps1'

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $installer,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count) {
    throw ($parseErrors | Out-String)
}

$requiredParameters = @(
    'InstallerPath',
    'HookVersion',
    'HookProtocolVersion',
    'SynapseCtrlVersion',
    'ExpectedFingerprint'
)
$parameterNames = @($ast.ParamBlock.Parameters | ForEach-Object {
    $_.Name.VariablePath.UserPath
})
foreach ($name in $requiredParameters) {
    if ($parameterNames -notcontains $name) {
        throw "Missing required metadata installer parameter: $name"
    }
}

$text = [IO.File]::ReadAllText($installer)
foreach ($name in @(
    'HookVersion',
    'HookProtocolVersion',
    'HookFingerprint',
    'InstalledByVersion',
    'InstalledAtUtc'
)) {
    if (-not $text.Contains($name)) {
        throw "Metadata installer does not persist/remove expected field: $name"
    }
}

if (-not $text.Contains('Get-FileHash')) {
    throw 'Metadata installer must verify the packaged hook fingerprint before mutation.'
}
if (-not $text.Contains('-Verb RunAs')) {
    throw 'Metadata installer must preserve the existing explicit elevation flow.'
}

Write-Host 'PASS: hook metadata installer parses and contains the managed version/fingerprint contract.'
