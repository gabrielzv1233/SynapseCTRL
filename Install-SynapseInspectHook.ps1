param(
    [switch]$Uninstall,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)

    return $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

if (-not (Test-IsAdministrator)) {
    $elevatedArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        # The parent handles the optional pause; the hidden child must never wait.
        "-NoPause"
    )

    if ($Uninstall) {
        $elevatedArgs += "-Uninstall"
    }

    try {
        $powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
            $powerShellExe = Join-Path $env:SystemRoot "Sysnative\WindowsPowerShell\v1.0\powershell.exe"
        }
        $child = Start-Process -FilePath $powerShellExe -Verb RunAs `
            -WindowStyle Hidden -ArgumentList $elevatedArgs -Wait -PassThru
        $resultCode = $child.ExitCode
        if ($resultCode -ne 0) {
            Write-Error "Elevated SynapseCTRL installer failed (exit $resultCode). Run this script from an Administrator PowerShell window to see the detailed error." -ErrorAction Continue
        } else {
            Write-Host "SynapseCTRL hook operation completed. Fully exit and reopen Synapse to apply changes."
        }
    } catch {
        Write-Error "Could not complete elevated installer: $_" -ErrorAction Continue
        $resultCode = 1
    }
    if (-not $NoPause) { Read-Host "Press Enter to continue..." | Out-Null }
    exit $resultCode
}

function Invoke-SynapseHook {

$StableExe = Join-Path `
    $env:ProgramFiles `
    "Razer\RazerAppEngine\RazerAppEngine.exe"

$InstallDir = Join-Path `
    $env:ProgramFiles `
    "SynapseCTRL"

$ShimExe = Join-Path `
    $InstallDir `
    "RazerInspectShim.exe"

$OldShimPs1 = Join-Path `
    $InstallDir `
    "RazerInspectShim.ps1"

$IFEOBase = (
    "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\" +
    "Image File Execution Options\RazerAppEngine.exe"
)

$FilterKey = Join-Path `
    $IFEOBase `
    "SynapseCTRL"

$debuggerCommand = "`"$ShimExe`""

# Check ownership and conflicts before compiling, replacing files, or changing IFEO.
$baseProperties = if (Test-Path -LiteralPath $IFEOBase) {
    Get-ItemProperty -LiteralPath $IFEOBase
} else { $null }
$filterProperties = if (Test-Path -LiteralPath $FilterKey) {
    Get-ItemProperty -LiteralPath $FilterKey
} else { $null }
if ($filterProperties -and (
    $filterProperties.FilterFullPath -ine $StableExe -or
    $filterProperties.Debugger -ine $debuggerCommand
)) {
    throw "The SynapseCTRL IFEO filter has unexpected values. No changes were made; inspect $FilterKey before repairing it."
}
if (-not $Uninstall) {
    if (-not (Test-Path -LiteralPath $StableExe -PathType Leaf)) {
        throw "Razer launcher not found: $StableExe"
    }
    if ($baseProperties.Debugger) {
        throw "A non-filtered IFEO Debugger already exists for RazerAppEngine.exe. No changes were made: $($baseProperties.Debugger)"
    }
    if (Test-Path -LiteralPath $IFEOBase) {
        foreach ($otherFilter in Get-ChildItem -LiteralPath $IFEOBase) {
            if ($otherFilter.PSChildName -ieq 'SynapseCTRL') { continue }
            $otherProperties = Get-ItemProperty -LiteralPath $otherFilter.PSPath
            if ($otherProperties.FilterFullPath -ieq $StableExe) {
                throw "Another IFEO filter already targets the stable Razer launcher: $($otherFilter.PSChildName). No changes were made."
            }
        }
    }
}

# Every removable file is a fixed immediate child of this exact install directory.
# Refuse redirected paths even when this script is invoked with elevation.
$expectedInstallDir = [IO.Path]::GetFullPath((Join-Path $env:ProgramFiles 'SynapseCTRL'))
if ([IO.Path]::GetFullPath($InstallDir) -ine $expectedInstallDir) {
    throw "Unexpected installation directory: $InstallDir"
}
foreach ($ownedPath in @($InstallDir, $ShimExe, $OldShimPs1)) {
    if (Test-Path -LiteralPath $ownedPath) {
        if ((Get-Item -LiteralPath $ownedPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing redirected installation path: $ownedPath"
        }
    }
}

if ($Uninstall) {
    if ($filterProperties) {
        # Preserve any unrelated values or nested filters in the same key.
        foreach ($valueName in @('Debugger', 'FilterFullPath', 'HookVersion', 'PreviousUseFilter', 'UseFilterWasPresent')) {
            Remove-ItemProperty -LiteralPath $FilterKey -Name $valueName -ErrorAction SilentlyContinue
        }
        $remainingKey = Get-Item -LiteralPath $FilterKey
        if ($remainingKey.ValueCount -eq 0 -and $remainingKey.SubKeyCount -eq 0) {
            Remove-Item -LiteralPath $FilterKey -Force
        }
    }

    if (Test-Path $ShimExe) {
        Remove-Item `
            -LiteralPath $ShimExe `
            -Force
    }

    if (Test-Path $OldShimPs1) {
        Remove-Item `
            -LiteralPath $OldShimPs1 `
            -Force
    }

    if (Test-Path $IFEOBase) {
        $remainingFilters = @(
            Get-ChildItem `
                -LiteralPath $IFEOBase
        )

        if ($remainingFilters.Count -eq 0 -and $filterProperties -and
            $baseProperties.UseFilter -eq 1 -and -not $baseProperties.Debugger) {
            if ($filterProperties.UseFilterWasPresent -eq 1) {
                Set-ItemProperty -LiteralPath $IFEOBase -Name UseFilter -Value $filterProperties.PreviousUseFilter
            } elseif ($baseProperties.UseFilter -eq 1) {
                Remove-ItemProperty -LiteralPath $IFEOBase -Name UseFilter -ErrorAction SilentlyContinue
            }
        }
    }

    if (
        (Test-Path $InstallDir) -and
        @(
            Get-ChildItem `
                -LiteralPath $InstallDir `
                -Force `
                -ErrorAction SilentlyContinue
        ).Count -eq 0
    ) {
        Remove-Item `
            -LiteralPath $InstallDir `
            -Force
    }

    Write-Host ""
    Write-Host "SynapseCTRL inspector hook removed."
    return
}

New-Item `
    -ItemType Directory `
    -Path $InstallDir `
    -Force | Out-Null

# Build a GUI-subsystem executable.
# Unlike powershell.exe, this shim has NO console of its own.
$source = @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class RazerInspectShim
{
    private const uint CREATE_NO_WINDOW = 0x08000000;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [DllImport(
        "kernel32.dll",
        CharSet = CharSet.Unicode,
        SetLastError = true
    )]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessW(
        string lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref STARTUPINFO lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr hObject);

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string programFiles =
                Environment.GetFolderPath(
                    Environment.SpecialFolder.ProgramFiles
                );

            string root = Path.Combine(
                programFiles,
                "Razer",
                "RazerAppEngine"
            );

            string versionedExe = FindNewestVersionedExe(root);

            if (String.IsNullOrEmpty(versionedExe))
            {
                LogError(
                    "Could not find a versioned RazerAppEngine.exe."
                );

                return 193;
            }

            List<string> forwarded = BuildArguments(args);

            StringBuilder commandLine = new StringBuilder();

            commandLine.Append(
                QuoteWindowsArgument(versionedExe)
            );

            for (int i = 0; i < forwarded.Count; i++)
            {
                commandLine.Append(' ');
                commandLine.Append(
                    QuoteWindowsArgument(forwarded[i])
                );
            }

            STARTUPINFO startup = new STARTUPINFO();
            startup.cb = Marshal.SizeOf(typeof(STARTUPINFO));

            PROCESS_INFORMATION processInfo;

            bool started = CreateProcessW(
                versionedExe,
                commandLine,
                IntPtr.Zero,
                IntPtr.Zero,

                // Do not let the Razer process inherit console/stdout
                // handles from anything that happened to launch us.
                false,

                // If RazerAppEngine is a console-subsystem executable,
                // explicitly create it without a console.
                CREATE_NO_WINDOW,

                IntPtr.Zero,
                Path.GetDirectoryName(versionedExe),
                ref startup,
                out processInfo
            );

            if (!started)
            {
                int error = Marshal.GetLastWin32Error();

                LogError(
                    "CreateProcessW failed: " +
                    error + " (" +
                    new Win32Exception(error).Message +
                    ")"
                );

                return error != 0 ? error : 194;
            }

            // We deliberately do not wait for Synapse.
            // Windows does not tie a normal child process lifetime
            // to its parent, so this shim exits immediately.
            if (processInfo.hThread != IntPtr.Zero)
            {
                CloseHandle(processInfo.hThread);
            }

            if (processInfo.hProcess != IntPtr.Zero)
            {
                CloseHandle(processInfo.hProcess);
            }

            return 0;
        }
        catch (Exception ex)
        {
            LogError(ex.ToString());
            return 195;
        }
    }

    private static List<string> BuildArguments(string[] args)
    {
        List<string> forwarded = new List<string>();
        forwarded.Add("--inspect=127.0.0.1:9229");

        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i] ?? String.Empty;
            // IFEO supplies the intercepted executable first; never launch it
            // again, because it is the filtered stable path and would recurse.
            if (i == 0 && Path.IsPathRooted(arg) && String.Equals(
                Path.GetFileName(arg), "RazerAppEngine.exe",
                StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            // Node also accepts underscores in option names. Never preserve an
            // incoming host/port, break-on-start, or inspector-disabling flag.
            string option = arg.Split('=')[0].Replace('_', '-');
            if (option.StartsWith("--inspect", StringComparison.OrdinalIgnoreCase) ||
                option.StartsWith("--no-inspect", StringComparison.OrdinalIgnoreCase) ||
                option.StartsWith("--debug", StringComparison.OrdinalIgnoreCase) ||
                option.StartsWith("--no-debug", StringComparison.OrdinalIgnoreCase))
            {
                if (arg.IndexOf('=') < 0 && i + 1 < args.Length)
                {
                    string next = args[i + 1] ?? String.Empty;
                    int port;
                    // Consume a separate --inspect-port value, or an endpoint
                    // after --inspect. Preserve ordinary application arguments.
                    if ((option.EndsWith("-port", StringComparison.OrdinalIgnoreCase) &&
                         !next.StartsWith("-", StringComparison.Ordinal)) ||
                        Int32.TryParse(next, out port) ||
                        (next.IndexOf(':') >= 0 && !next.StartsWith("-", StringComparison.Ordinal)))
                    {
                        i++;
                    }
                }
                continue;
            }
            forwarded.Add(arg);
        }
        return forwarded;
    }

    private static string FindNewestVersionedExe(string root)
    {
        if (!Directory.Exists(root))
        {
            return null;
        }

        string[] directories = Directory.GetDirectories(
            root,
            "app-*",
            SearchOption.TopDirectoryOnly
        );

        Version newestVersion = null;
        string newestExe = null;

        for (int i = 0; i < directories.Length; i++)
        {
            string directory = directories[i];
            string name = Path.GetFileName(directory);

            if (
                String.IsNullOrEmpty(name) ||
                !name.StartsWith(
                    "app-",
                    StringComparison.OrdinalIgnoreCase
                )
            )
            {
                continue;
            }

            Version version;

            if (!Version.TryParse(name.Substring(4), out version))
            {
                continue;
            }

            string exe = Path.Combine(
                directory,
                "RazerAppEngine.exe"
            );

            if (!File.Exists(exe))
            {
                continue;
            }

            if (
                newestVersion == null ||
                version > newestVersion
            )
            {
                newestVersion = version;
                newestExe = exe;
            }
        }

        return newestExe;
    }

    private static string QuoteWindowsArgument(string value)
    {
        if (value == null)
        {
            return "\"\"";
        }

        if (value.Length == 0)
        {
            return "\"\"";
        }

        bool needsQuotes = false;

        for (int i = 0; i < value.Length; i++)
        {
            char c = value[i];

            if (
                Char.IsWhiteSpace(c) ||
                c == '"'
            )
            {
                needsQuotes = true;
                break;
            }
        }

        if (!needsQuotes)
        {
            return value;
        }

        StringBuilder result = new StringBuilder();
        result.Append('"');

        int slashCount = 0;

        for (int i = 0; i < value.Length; i++)
        {
            char c = value[i];

            if (c == '\\')
            {
                slashCount++;
                continue;
            }

            if (c == '"')
            {
                result.Append(
                    new string(
                        '\\',
                        slashCount * 2 + 1
                    )
                );

                result.Append('"');
                slashCount = 0;
                continue;
            }

            if (slashCount > 0)
            {
                result.Append(
                    new string('\\', slashCount)
                );

                slashCount = 0;
            }

            result.Append(c);
        }

        if (slashCount > 0)
        {
            result.Append(
                new string(
                    '\\',
                    slashCount * 2
                )
            );
        }

        result.Append('"');

        return result.ToString();
    }

    private static void LogError(string message)
    {
        try
        {
            string directory = Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.CommonApplicationData
                ),
                "SynapseCTRL"
            );

            Directory.CreateDirectory(directory);

            File.AppendAllText(
                Path.Combine(
                    directory,
                    "shim-error.log"
                ),
                DateTime.Now.ToString("O") +
                Environment.NewLine +
                message +
                Environment.NewLine +
                Environment.NewLine
            );
        }
        catch
        {
        }
    }
}
'@

$tempShim = Join-Path `
    $InstallDir `
    ("RazerInspectShim-" + [Guid]::NewGuid().ToString('N') + ".exe")

try {
    Add-Type `
        -TypeDefinition $source `
        -Language CSharp `
        -OutputAssembly $tempShim `
        -OutputType WindowsApplication

    if (-not (Test-Path $tempShim)) {
        throw "C# compiler did not produce the launcher executable."
    }

    Copy-Item `
        -LiteralPath $tempShim `
        -Destination $ShimExe `
        -Force
}
finally {
    Remove-Item `
        -LiteralPath $tempShim `
        -Force `
        -ErrorAction SilentlyContinue
}

# Delete the old PowerShell-based shim if this is an upgrade.
Remove-Item `
    -LiteralPath $OldShimPs1 `
    -Force `
    -ErrorAction SilentlyContinue

New-Item `
    -Path $IFEOBase `
    -Force | Out-Null

New-ItemProperty `
    -Path $IFEOBase `
    -Name UseFilter `
    -PropertyType DWord `
    -Value 1 `
    -Force | Out-Null

New-Item `
    -Path $FilterKey `
    -Force | Out-Null

if (-not $filterProperties) {
    $useFilterWasPresent = [int]($null -ne $baseProperties -and $null -ne $baseProperties.UseFilter)
    New-ItemProperty -LiteralPath $FilterKey -Name UseFilterWasPresent -PropertyType DWord -Value $useFilterWasPresent -Force | Out-Null
    if ($useFilterWasPresent) {
        New-ItemProperty -LiteralPath $FilterKey -Name PreviousUseFilter -PropertyType DWord -Value $baseProperties.UseFilter -Force | Out-Null
    }
}
New-ItemProperty -LiteralPath $FilterKey -Name HookVersion -PropertyType DWord -Value 2 -Force | Out-Null

New-ItemProperty `
    -Path $FilterKey `
    -Name FilterFullPath `
    -PropertyType String `
    -Value $StableExe `
    -Force | Out-Null

# The critical change:
# IFEO now invokes a GUI-subsystem .exe directly.
# powershell.exe is no longer anywhere in the normal Synapse launch path.
$debuggerCommand = "`"$ShimExe`""

New-ItemProperty `
    -Path $FilterKey `
    -Name Debugger `
    -PropertyType String `
    -Value $debuggerCommand `
    -Force | Out-Null

Write-Host ""
Write-Host "Installed native no-console Synapse inspector hook."
Write-Host ""
Write-Host "IFEO launcher:"
Write-Host "  $ShimExe"
Write-Host ""
Write-Host "Synapse will receive:"
Write-Host "  --inspect=127.0.0.1:9229"
Write-Host ""
Write-Host "No PowerShell process participates in normal Synapse launches."
Write-Host ""
Write-Host "Fully Exit Synapse once, then open the normal Razer Synapse shortcut."
Write-Host ""
Write-Host "Verify inspector:"
Write-Host "  Invoke-RestMethod http://127.0.0.1:9229/json/list"
Write-Host ""
Write-Host "Verify no shim is lingering:"
Write-Host "  Get-Process RazerInspectShim -ErrorAction SilentlyContinue"
Write-Host ""
Write-Host "That command should return nothing after Synapse has started."
Write-Host ""
}

try {
    Invoke-SynapseHook
    $resultCode = 0
} catch {
    Write-Error "SynapseCTRL hook operation failed: $_" -ErrorAction Continue
    $resultCode = 1
}
if (-not $NoPause) { Read-Host "Press Enter to continue..." | Out-Null }
exit $resultCode
