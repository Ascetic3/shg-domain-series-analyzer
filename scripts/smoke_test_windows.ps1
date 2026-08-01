[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$version = "0.1.0"
$portableExe = Join-Path $repoRoot "dist\SHGSeriesAnalyzer\SHGSeriesAnalyzer.exe"
$setupPath = Join-Path $repoRoot "release\SHG-Series-Analyzer-Setup-$version.exe"
$testParent = Join-Path $repoRoot ".test_tmp"
$testRoot = Join-Path $testParent ("windows-installer-" + [guid]::NewGuid().ToString("N"))
$installDirectory = Join-Path $testRoot "installed\SHG Series Analyzer"
$resultDirectory = Join-Path $testRoot "user-results"
$sentinelPath = Join-Path $resultDirectory "keep-after-uninstall.txt"
$programsDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
$shortcutDirectory = Join-Path $programsDirectory "SHG Series Analyzer"
$shortcutPath = Join-Path $shortcutDirectory "SHG Series Analyzer.lnk"
$uninstallRegistryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{54F74C72-BF25-4D60-97E6-85759D648DA7}_is1"
$completed = $false
$uninstalled = $false

function Invoke-BoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutMilliseconds = 120000
    )

    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit($TimeoutMilliseconds)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Process timed out: $FilePath"
    }
    if ($process.ExitCode -ne 0) {
        throw "Process failed with exit code $($process.ExitCode): $FilePath"
    }
}

function Invoke-AppSmokeTest {
    param([Parameter(Mandatory = $true)][string]$Executable)
    Invoke-BoundedProcess -FilePath $Executable -Arguments @("--smoke-test") -TimeoutMilliseconds 30000
}

Set-Location -LiteralPath $repoRoot

if (-not (Test-Path -LiteralPath $portableExe)) {
    throw "Portable executable was not found: $portableExe"
}
if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Installer was not found: $setupPath"
}
if (Test-Path -LiteralPath $uninstallRegistryPath) {
    throw "An existing SHG Series Analyzer installation was found. Refusing to replace it during the smoke test."
}
if (Test-Path -LiteralPath $shortcutDirectory) {
    throw "An existing SHG Series Analyzer Start menu group was found. Refusing to replace it during the smoke test."
}

New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
Set-Content -LiteralPath $sentinelPath -Value "Synthetic smoke-test sentinel; not application output." -Encoding UTF8

try {
    Invoke-AppSmokeTest -Executable $portableExe

    $installArguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/MERGETASKS=!desktopicon",
        "/DIR=`"$installDirectory`""
    )
    Invoke-BoundedProcess -FilePath $setupPath -Arguments $installArguments

    $installedExe = Join-Path $installDirectory "SHGSeriesAnalyzer.exe"
    if (-not (Test-Path -LiteralPath $installedExe)) {
        throw "Installed executable was not found: $installedExe"
    }
    if (-not (Test-Path -LiteralPath $shortcutPath)) {
        throw "Start menu shortcut was not created: $shortcutPath"
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcutTarget = [System.IO.Path]::GetFullPath($shortcut.TargetPath)
    $expectedTarget = [System.IO.Path]::GetFullPath($installedExe)
    if (-not $shortcutTarget.Equals($expectedTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Shortcut target is incorrect: $shortcutTarget"
    }

    Invoke-AppSmokeTest -Executable $installedExe

    $uninstaller = Get-ChildItem -LiteralPath $installDirectory -Filter "unins*.exe" | Select-Object -First 1
    if ($null -eq $uninstaller) {
        throw "Inno Setup uninstaller was not found in $installDirectory"
    }
    Invoke-BoundedProcess -FilePath $uninstaller.FullName -Arguments @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    $uninstalled = $true

    if (Test-Path -LiteralPath $installedExe) {
        throw "The installed application remains after uninstall: $installedExe"
    }
    if (-not (Test-Path -LiteralPath $sentinelPath)) {
        throw "The uninstaller removed the external user-results sentinel."
    }
    if (Test-Path -LiteralPath $shortcutPath) {
        throw "The Start menu shortcut remains after uninstall: $shortcutPath"
    }

    $completed = $true
    Write-Host "Portable, install, shortcut, installed-app, uninstall, and user-results preservation smoke tests passed."
}
finally {
    if (-not $uninstalled) {
        $cleanupUninstaller = Get-ChildItem -LiteralPath $installDirectory -Filter "unins*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $cleanupUninstaller) {
            try {
                Invoke-BoundedProcess -FilePath $cleanupUninstaller.FullName -Arguments @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
                $uninstalled = $true
            }
            catch {
                Write-Warning "Automatic cleanup uninstall failed: $_"
            }
        }
    }

    $testRootFull = [System.IO.Path]::GetFullPath($testRoot)
    $testParentPrefix = [System.IO.Path]::GetFullPath($testParent).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $testRootFull.StartsWith($testParentPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a path outside the smoke-test directory: $testRootFull"
    }
    if ($uninstalled -and -not (Test-Path -LiteralPath $uninstallRegistryPath) -and (Test-Path -LiteralPath $testRootFull)) {
        Remove-Item -LiteralPath $testRootFull -Recurse -Force
    }
    elseif (Test-Path -LiteralPath $testRootFull) {
        Write-Warning "Smoke-test files were preserved for diagnosis: $testRootFull"
    }

    if ($completed) {
        if (Test-Path -LiteralPath $testRootFull) {
            throw "Smoke-test cleanup did not remove the temporary directory: $testRootFull"
        }
    }
}
