<#
.SYNOPSIS
Run GridLens tests from any working directory (PowerShell 5.1 or later).
.DESCRIPTION
Uses only the manually created .venv in the repository's parent directory.
Does not create environments, install packages, or change execution policies.
GUI tests need an interactive desktop. PowerFactory itself is not required.
.EXAMPLE
.\run_tests.ps1
.EXAMPLE
.\run_tests.ps1 -PyQtOnly
.EXAMPLE
.\run_tests.ps1 -NoGui
.EXAMPLE
.\run_tests.ps1 -GuiOnly
.EXAMPLE
.\run_tests.ps1 -PytestArgs @('-k', 'n1', '--maxfail=1')
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$PyQtOnly,
    [switch]$NoGui,
    [switch]$GuiOnly,
    [ValidateRange(1, 3600)]
    [int]$GuiTimeoutSeconds = 60,
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = 'Stop'
# Native exit codes are handled explicitly, including on PowerShell 7.3+.
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$exitCode = 1
$locationChanged = $false
try {
    if (([int]$PyQtOnly.IsPresent + [int]$NoGui.IsPresent + [int]$GuiOnly.IsPresent) -gt 1) {
        throw 'Use only one of -PyQtOnly, -NoGui or -GuiOnly.'
    }
    $venvDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv'
    $testPython = Join-Path $venvDirectory 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $testPython -PathType Leaf)) {
        $testPython = Join-Path $venvDirectory 'bin/python'
    }
    if (-not (Test-Path -LiteralPath $testPython -PathType Leaf)) {
        throw "The manually created parent environment was not found: $venvDirectory"
    }
    Write-Host "Using Python: $testPython"
    & $testPython -c "import pytest; print('pytest ' + pytest.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "pytest is unavailable. Install development dependencies manually (pip 25.1 or newer): & `"$testPython`" -m pip install --group dev"
    }
    if ($PyQtOnly) {
        & $testPython -c "import importlib.util, sys; sys.exit(0 if any(importlib.util.find_spec(name) is not None for name in ('PyQt6', 'PyQt5')) else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw 'PyQt6/PyQt5 is unavailable in the selected Python. Install PyQt manually before using -PyQtOnly.'
        }
    }

    Push-Location -LiteralPath $PSScriptRoot
    $locationChanged = $true
    $testArguments = @('-m', 'pytest', '-q', "--gui-timeout=$GuiTimeoutSeconds")
    if ($GuiOnly) {
        $testArguments = @('-m', 'pytest', '-vv', '--require-gui', '-m', 'gui and not optional_qt', "--gui-timeout=$GuiTimeoutSeconds")
    }
    if ($NoGui) {
        $testArguments += @('-m', 'not gui')
    }
    if ($PyQtOnly) {
        $testArguments += 'tests/test_preview_pyqt_dialog.py'
    }
    $testArguments += $PytestArgs
    & $testPython @testArguments
    $exitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $exitCode = 1
}
finally {
    if ($locationChanged) {
        Pop-Location
    }
}
exit $exitCode
