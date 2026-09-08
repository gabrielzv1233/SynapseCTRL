param(
    [switch]$Uninstall
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
        "-File", "`"$PSCommandPath`""
    )

    if ($Uninstall) {
        $elevatedArgs += "-Uninstall"
    }

    Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -ArgumentList $elevatedArgs

    exit
}

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

if ($Uninstall) {
    if (Test-Path $FilterKey) {
        Remove-Item `
            $FilterKey `
            -Recurse `
            -Force
    }

    if (Test-Path $ShimExe) {
        Remove-Item `
            $ShimExe `
            -Force
    }

    if (Test-Path $OldShimPs1) {
        Remove-Item `
            $OldShimPs1 `
            -Force
    }

    if (Test-Path $IFEOBase) {
        $remainingFilters = @(
            Get-ChildItem `
                $IFEOBase `
                -ErrorAction SilentlyContinue |
            Where-Object {
                $props = Get-ItemProperty `
                    $_.PSPath `
                    -ErrorAction SilentlyContinue

                $props.FilterFullPath -or $props.Debugger
            }
        )

        if ($remainingFilters.Count -eq 0) {
            Remove-ItemProperty `
                $IFEOBase `
                -Name UseFilter `
                -ErrorAction SilentlyContinue
        }
    }

    if (
        (Test-Path $InstallDir) -and
        @(
            Get-ChildItem `
                $InstallDir `
                -Force `
                -ErrorAction SilentlyContinue
        ).Count -eq 0
    ) {
        Remove-Item `
            $InstallDir `
            -Force
    }

    Write-Host ""
    Write-Host "SynapseCTRL inspector hook removed."
    exit
}

if (-not (Test-Path $StableExe)) {
    throw "Razer launcher not found: $StableExe"
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

            List<string> forwarded = new List<string>();

            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i] ?? String.Empty;

                // IFEO normally supplies the intercepted executable
                // as argv[0] to the debugger. Do not forward it.
                if (
                    i == 0 &&
                    String.Equals(
                        Path.GetFileName(arg),
                        "RazerAppEngine.exe",
                        StringComparison.OrdinalIgnoreCase
                    ) &&
                    Path.IsPathRooted(arg)
                )
                {
                    continue;
                }

                forwarded.Add(arg);
            }

            bool hasInspector = false;

            for (int i = 0; i < forwarded.Count; i++)
            {
                string arg = forwarded[i];

                if (
                    arg.StartsWith(
                        "--inspect",
                        StringComparison.OrdinalIgnoreCase
                    )
                )
                {
                    hasInspector = true;
                    break;
                }
            }

            if (!hasInspector)
            {
                forwarded.Insert(
                    0,
                    "--inspect=127.0.0.1:9229"
                );
            }

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
    $env:TEMP `
    "RazerInspectShim-$PID.exe"

Remove-Item `
    $tempShim `
    -Force `
    -ErrorAction SilentlyContinue

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
        $tempShim `
        $ShimExe `
        -Force
}
finally {
    Remove-Item `
        $tempShim `
        -Force `
        -ErrorAction SilentlyContinue
}

# Delete the old PowerShell-based shim if this is an upgrade.
Remove-Item `
    $OldShimPs1 `
    -Force `
    -ErrorAction SilentlyContinue

New-Item `
    -Path $IFEOBase `
    -Force | Out-Null

$existingTopDebugger = (
    Get-ItemProperty `
        $IFEOBase `
        -Name Debugger `
        -ErrorAction SilentlyContinue
).Debugger

if ($existingTopDebugger) {
    throw @"
A non-filtered IFEO Debugger is already configured for RazerAppEngine.exe:

$existingTopDebugger

I did not overwrite it.
"@
}

New-ItemProperty `
    -Path $IFEOBase `
    -Name UseFilter `
    -PropertyType DWord `
    -Value 1 `
    -Force | Out-Null

New-Item `
    -Path $FilterKey `
    -Force | Out-Null

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
Read-Host "Press Enter to continue..."