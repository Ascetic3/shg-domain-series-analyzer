[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$version = "0.1.0"
$distDirectory = Join-Path $repoRoot "dist\SHGSeriesAnalyzer"
$portableExe = Join-Path $distDirectory "SHGSeriesAnalyzer.exe"
$releaseDirectory = Join-Path $repoRoot "release"
$setupPath = Join-Path $releaseDirectory "SHG-Series-Analyzer-Setup-$version.exe"
$portableZip = Join-Path $releaseDirectory "SHG-Series-Analyzer-Portable-$version.zip"
$checksumsPath = Join-Path $releaseDirectory "SHA256SUMS.txt"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Remove-GeneratedDirectory {
    param([Parameter(Mandatory = $true)][ValidateSet("build", "dist", "release")][string]$Name)

    $target = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Name))
    $rootPrefix = $repoRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the repository: $target"
    }
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

function Find-InnoCompiler {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    throw "Inno Setup 6 compiler ISCC.exe was not found. Install JRSoftware.InnoSetup with winget and rerun the build."
}

function Invoke-SmokeExecutable {
    param([Parameter(Mandatory = $true)][string]$Executable)

    $process = Start-Process -FilePath $Executable -ArgumentList "--smoke-test" -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Smoke test timed out after 30 seconds: $Executable"
    }
    if ($process.ExitCode -ne 0) {
        throw "Smoke test failed with exit code $($process.ExitCode): $Executable"
    }
}

Set-Location -LiteralPath $repoRoot

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Virtual environment Python was not found at .venv\Scripts\python.exe"
}

$pyproject = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "pyproject.toml")
if ($pyproject -notmatch '(?m)^version\s*=\s*"0\.1\.0"\s*$') {
    throw "pyproject.toml version must be 0.1.0 for this release build."
}

foreach ($directory in @("build", "dist", "release")) {
    Remove-GeneratedDirectory -Name $directory
}

if (-not $SkipDependencyInstall) {
    Invoke-NativeCommand -FilePath $pythonPath -Arguments @("-m", "pip", "install", "-e", ".[test,build]")
}

if (-not $SkipTests) {
    Invoke-NativeCommand -FilePath $pythonPath -Arguments @("-m", "pytest")
}

Invoke-NativeCommand -FilePath $pythonPath -Arguments @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--workpath", "build",
    "--distpath", "dist",
    "packaging\SHGSeriesAnalyzer.spec"
)

if (-not (Test-Path -LiteralPath $portableExe)) {
    throw "PyInstaller output was not created: $portableExe"
}
Invoke-SmokeExecutable -Executable $portableExe

$isccPath = Find-InnoCompiler
Invoke-NativeCommand -FilePath $isccPath -Arguments @("installer\SHGSeriesAnalyzer.iss")

if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Inno Setup output was not created: $setupPath"
}

Compress-Archive -Path (Join-Path $distDirectory "*") -DestinationPath $portableZip -CompressionLevel Optimal

$releaseFiles = @($setupPath, $portableZip)
$checksumLines = foreach ($file in $releaseFiles) {
    $hash = Get-FileHash -LiteralPath $file -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant()) *$([System.IO.Path]::GetFileName($file))"
}
[System.IO.File]::WriteAllLines($checksumsPath, $checksumLines, [System.Text.UTF8Encoding]::new($false))

$artifacts = Get-Item -LiteralPath @($setupPath, $portableZip, $checksumsPath)
$artifacts | Select-Object FullName, Length | Format-Table -AutoSize
