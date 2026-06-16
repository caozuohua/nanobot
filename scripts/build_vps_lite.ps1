[CmdletBinding()]
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputDir = [IO.Path]::GetFullPath((Join-Path $repoRoot "dist\vps-lite"))
$venvDir = [IO.Path]::GetFullPath((Join-Path $repoRoot ".venv-vps-lite"))
$repoPrefix = $repoRoot.TrimEnd('\') + '\'

function Reset-Directory {
    param([Parameter(Mandatory)][string]$Path)

    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean path outside repository: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolved | Out-Null
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($ArgumentList -join ' ')"
    }
}

Reset-Directory -Path $outputDir
if (Test-Path -LiteralPath $venvDir) {
    $resolvedVenv = [IO.Path]::GetFullPath($venvDir)
    if (-not $resolvedVenv.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean path outside repository: $resolvedVenv"
    }
    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

Push-Location $repoRoot
$previousBuildProfile = $env:NANOBOT_BUILD_PROFILE
$previousRuntimeProfile = $env:NANOBOT_PROFILE
$previousArtifact = $env:NANOBOT_VPS_LITE_WHEEL
$previousSkipWebui = $env:NANOBOT_SKIP_WEBUI_BUILD
try {
    Invoke-Native -FilePath $Python -ArgumentList @("-m", "venv", $venvDir)
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    $nanobotCli = Join-Path $venvDir "Scripts\nanobot.exe"

    Invoke-Native -FilePath $venvPython -ArgumentList @(
        "-m", "pip", "install", "--upgrade", "pip", "build", "hatchling", "packaging",
        "pytest", "pytest-asyncio"
    )

    $env:NANOBOT_BUILD_PROFILE = "vps-lite"
    $env:NANOBOT_SKIP_WEBUI_BUILD = $null
    Invoke-Native -FilePath $venvPython -ArgumentList @(
        "-m", "build", "--wheel", "--outdir", $outputDir
    )

    $wheels = @(Get-ChildItem -LiteralPath $outputDir -Filter "*.whl")
    if ($wheels.Count -ne 1) {
        throw "Expected exactly one wheel in $outputDir, found $($wheels.Count)"
    }
    $wheel = $wheels[0].FullName

    Invoke-Native -FilePath $venvPython -ArgumentList @(
        "-m", "pip", "install", "--force-reinstall", $wheel
    )

    $env:NANOBOT_PROFILE = "vps-lite"
    Invoke-Native -FilePath $nanobotCli -ArgumentList @("--help")

    $env:NANOBOT_VPS_LITE_WHEEL = $wheel
    Invoke-Native -FilePath $venvPython -ArgumentList @(
        "-m", "pytest", "tests/build/test_vps_lite_artifact.py", "-v"
    )

    Write-Host "VPS Lite wheel verified: $wheel"
}
finally {
    $env:NANOBOT_BUILD_PROFILE = $previousBuildProfile
    $env:NANOBOT_PROFILE = $previousRuntimeProfile
    $env:NANOBOT_VPS_LITE_WHEEL = $previousArtifact
    $env:NANOBOT_SKIP_WEBUI_BUILD = $previousSkipWebui
    Pop-Location
}
