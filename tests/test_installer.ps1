# Offline installer validation. Never execute the installer, mutate the registry,
# elevate, or launch/stop Synapse. Only compile and inspect the embedded native shim.
$ErrorActionPreference = 'Stop'
$installer = Join-Path (Split-Path -Parent $PSScriptRoot) 'Install-SynapseInspectHook.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$assignment = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.VariablePath.UserPath -eq 'source'
}, $true)
$source = $assignment.Right.Expression.Value
if (-not $source) { throw 'Embedded C# source was not found.' }

function Assert-Equal($actual, $expected, $label) {
    if ($actual -cne $expected) { throw "$label expected <$expected>, got <$actual>." }
}

# Evaluate only the operation function with an in-memory registry/filesystem.
# Any unmocked attempted install mutation fails the test before it can run.
& {
    $operation = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-SynapseHook'
    }, $true)
    Invoke-Expression $operation.Extent.Text
    $basePath = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\RazerAppEngine.exe'
    $ownPath = Join-Path $basePath 'SynapseCTRL'
    $installPath = Join-Path $env:ProgramFiles 'SynapseCTRL'
    $shimPath = Join-Path $installPath 'RazerInspectShim.exe'
    $stablePath = Join-Path $env:ProgramFiles 'Razer\RazerAppEngine\RazerAppEngine.exe'
    $state = @{}
    function Reset-Fixture {
        $state.Clear()
        $state.Base = @{ UseFilter = 1 }
        $state.Filters = @{ SynapseCTRL = @{ FilterFullPath = $stablePath; Debugger = "`"$shimPath`"" } }
        $state.Files = @{ $stablePath = $true; $installPath = $true; $shimPath = $true }
        $state.Mutations = [Collections.Generic.List[string]]::new()
    }
    function Test-Path($LiteralPath, $Path, $PathType) {
        $selected = if ($LiteralPath) { $LiteralPath } else { $Path }
        if ($selected -eq $basePath) { return $true }
        if ($selected -eq $ownPath) { return $state.Filters.ContainsKey('SynapseCTRL') }
        return $state.Files.ContainsKey($selected)
    }
    function Get-ItemProperty($LiteralPath) {
        if ($LiteralPath -eq $basePath) { return [pscustomobject]$state.Base }
        $name = Split-Path -Leaf $LiteralPath
        if ($state.Filters.ContainsKey($name)) { return [pscustomobject]$state.Filters[$name] }
        throw "Unexpected registry read: $LiteralPath"
    }
    function Get-ChildItem($LiteralPath, [switch]$Force) {
        if ($LiteralPath -eq $basePath) {
            foreach ($name in $state.Filters.Keys) {
                [pscustomobject]@{ PSChildName = $name; PSPath = Join-Path $basePath $name }
            }
        } elseif ($LiteralPath -eq $installPath) {
            foreach ($name in $state.Files.Keys) {
                if ($name.StartsWith($installPath + '\')) { [pscustomobject]@{ FullName = $name } }
            }
        } else { throw "Unexpected directory enumeration: $LiteralPath" }
    }
    function Get-Item($LiteralPath, [switch]$Force) {
        if ($LiteralPath -eq $ownPath) {
            return [pscustomobject]@{ ValueCount = $state.Filters.SynapseCTRL.Count; SubKeyCount = 0 }
        }
        return [pscustomobject]@{ Attributes = [IO.FileAttributes]::Normal }
    }
    function Remove-ItemProperty($LiteralPath, $Name, $ErrorAction) {
        $state.Mutations.Add("remove-value:$LiteralPath/$Name")
        if ($LiteralPath -eq $basePath) { $state.Base.Remove($Name) }
        elseif ($LiteralPath -eq $ownPath) { $state.Filters.SynapseCTRL.Remove($Name) }
        else { throw "Unexpected registry deletion: $LiteralPath" }
    }
    function Set-ItemProperty($LiteralPath, $Name, $Value) {
        if ($LiteralPath -ne $basePath -or $Name -ne 'UseFilter') { throw 'Unexpected registry set' }
        $state.Mutations.Add("set-value:$Name")
        $state.Base[$Name] = $Value
    }
    function Remove-Item($LiteralPath, [switch]$Force, $ErrorAction) {
        $state.Mutations.Add("remove:$LiteralPath")
        if ($LiteralPath -eq $ownPath) { $state.Filters.Remove('SynapseCTRL') }
        elseif ($state.Files.ContainsKey($LiteralPath)) { $state.Files.Remove($LiteralPath) }
        else { throw "Unexpected file deletion: $LiteralPath" }
    }
    function New-Item { throw 'Unexpected mutation: New-Item' }
    function New-ItemProperty { throw 'Unexpected mutation: New-ItemProperty' }
    function Copy-Item { throw 'Unexpected mutation: Copy-Item' }
    function Add-Type { throw 'Unexpected compilation before conflict check' }
    function Start-Process { throw 'Unexpected process launch' }
    function Assert-Conflict($expected) {
        try { Invoke-SynapseHook; throw 'Expected preflight conflict' }
        catch {
            if ($_.Exception.Message -notlike $expected) { throw }
        }
        Assert-Equal $state.Mutations.Count 0 'conflict must not mutate machine state'
    }

    $Uninstall = $false
    Reset-Fixture
    $state.Base.Debugger = 'unrelated.exe'
    Assert-Conflict '*non-filtered IFEO Debugger*'
    Reset-Fixture
    $state.Filters.OtherTool = @{ FilterFullPath = $stablePath; Debugger = 'unrelated.exe' }
    Assert-Conflict '*Another IFEO filter*'
    Reset-Fixture
    $state.Filters.SynapseCTRL.Debugger = 'unrelated.exe'
    Assert-Conflict '*unexpected values*'
    $Uninstall = $true
    Assert-Conflict '*unexpected values*'

    Reset-Fixture
    $state.Filters.OtherTool = @{ FilterFullPath = 'C:\Other\RazerAppEngine.exe'; Debugger = 'other.exe' }
    Invoke-SynapseHook
    Assert-Equal $state.Filters.ContainsKey('SynapseCTRL') $false 'owned filter removed'
    Assert-Equal $state.Filters.OtherTool.Debugger 'other.exe' 'unrelated filter preserved'
    Assert-Equal $state.Base.UseFilter 1 'filter support preserved for other tools'

    Reset-Fixture
    $state.Filters.SynapseCTRL.UnrelatedValue = 'preserve'
    Invoke-SynapseHook
    Assert-Equal $state.Filters.SynapseCTRL.UnrelatedValue 'preserve' 'unrelated value in owned filter preserved'
    Assert-Equal $state.Filters.SynapseCTRL.ContainsKey('Debugger') $false 'owned debugger removed'

    Reset-Fixture
    $state.Filters.SynapseCTRL.UseFilterWasPresent = 1
    $state.Filters.SynapseCTRL.PreviousUseFilter = 0
    Invoke-SynapseHook
    Assert-Equal $state.Base.UseFilter 0 'previous UseFilter restored'

    Reset-Fixture
    $state.Base.Debugger = 'other.exe'
    Invoke-SynapseHook
    Assert-Equal $state.Base.Debugger 'other.exe' 'top-level debugger preserved on uninstall'
    Assert-Equal $state.Base.UseFilter 1 'uninstall must not enable unrelated top-level debugger'
    Write-Host 'PASS: installer conflict preflight and conservative uninstall pass in-memory registry fixtures.'
}

$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $temporaryBase ('SynapseCTRL-installer-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    $assemblyPath = Join-Path $testRoot 'RazerInspectShim.exe'
    Add-Type -TypeDefinition $source -Language CSharp -OutputAssembly $assemblyPath -OutputType WindowsApplication
    $bytes = [IO.File]::ReadAllBytes($assemblyPath)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    Assert-Equal ([BitConverter]::ToUInt16($bytes, $peOffset + 24 + 68)) 2 'GUI subsystem'
    # Load bytes so the temporary executable is never run and is not file-locked.
    $assembly = [Reflection.Assembly]::Load($bytes)
    $shimType = $assembly.GetType('RazerInspectShim')
    $flags = [Reflection.BindingFlags]'NonPublic,Static'
    $build = $shimType.GetMethod('BuildArguments', $flags)
    $newest = $shimType.GetMethod('FindNewestVersionedExe', $flags)
    $quote = $shimType.GetMethod('QuoteWindowsArgument', $flags)

    $inputArguments = [string[]]@(
        'C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe',
        '--inspect=0.0.0.0:9999', '--inspect-port', '0.0.0.0:8888',
        '--inspect_brk=0.0.0.0:1234', '--inspect_port=0.0.0.0:7777',
        '--no-inspect', '--debug=0.0.0.0:5858',
        '--inspect', '0.0.0.0:7000', '--inspect-wait',
        '--hidden', 'an argument with spaces', 'last'
    )
    $actual = $build.Invoke($null, [object[]]@(,$inputArguments))
    Assert-Equal ($actual -join '|') '--inspect=127.0.0.1:9229|--hidden|an argument with spaces|last' 'sanitized inspector arguments'
    $simple = $build.Invoke($null, [object[]]@(,[string[]]@('--inspect', '--hidden')))
    Assert-Equal ($simple -join '|') '--inspect=127.0.0.1:9229|--hidden' 'bare inspector'
    $terminator = $build.Invoke($null, [object[]]@(,[string[]]@('--', 'file')))
    Assert-Equal ($terminator -join '|') '--inspect=127.0.0.1:9229|--|file' 'option terminator'

    foreach ($version in @('4.0.99', '4.0.1000', '4.0.999', '100-preview')) {
        $directory = Join-Path $testRoot "app-$version"
        New-Item -ItemType Directory -Path $directory | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $directory 'RazerAppEngine.exe'), [byte[]]@())
    }
    New-Item -ItemType Directory -Path (Join-Path $testRoot 'app-9.0.0') | Out-Null
    Assert-Equal ($newest.Invoke($null, [object[]][string[]]@($testRoot))) (Join-Path $testRoot 'app-4.0.1000\RazerAppEngine.exe') 'numeric version selection with incomplete update'
    Assert-Equal ($newest.Invoke($null, [object[]][string[]]@((Join-Path $testRoot 'missing')))) $null 'missing installation'

    # Windows' native parser provides independent verification of argument quoting.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ShimArgumentParser {
    [DllImport("shell32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern IntPtr CommandLineToArgvW(string commandLine, out int argc);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    public static string ParseSecond(string commandLine) {
        int argc;
        IntPtr argv = CommandLineToArgvW(commandLine, out argc);
        if (argv == IntPtr.Zero) throw new Exception("CommandLineToArgvW failed");
        try {
            if (argc != 2) throw new Exception("Expected exactly two arguments, got " + argc);
            return Marshal.PtrToStringUni(Marshal.ReadIntPtr(argv, IntPtr.Size));
        } finally { LocalFree(argv); }
    }
}
'@
    foreach ($argument in @('', 'plain', 'with spaces', 'embedded"quote', 'C:\space folder\', '\\host\folder with spaces\', 'a\\"b')) {
        $quoted = $quote.Invoke($null, [object[]][string[]]@($argument))
        Assert-Equal ([ShimArgumentParser]::ParseSecond("shim.exe $quoted")) $argument 'Windows argument round trip'
    }
    Write-Host 'PASS: installer parses, native shim compiles as GUI, inspector flags stay loopback, newest version and Windows argument quoting work.'
} finally {
    # Verify the resolved exact test target stays under TEMP before recursive cleanup.
    $resolvedRoot = [IO.Path]::GetFullPath($testRoot)
    $safePrefix = $temporaryBase.TrimEnd('\') + '\'
    if (-not $resolvedRoot.StartsWith($safePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolvedRoot) -notlike 'SynapseCTRL-installer-test-*') {
        throw "Refusing unexpected test cleanup path: $resolvedRoot"
    }
    Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
}
