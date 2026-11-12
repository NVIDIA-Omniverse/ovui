# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Make the Visual Studio CMake generator compile with the MSVC 14.38 toolset.
#
# Kit ships the MSVC 14.38 toolset and its C++ runtime. The windows-2022 runner
# image has only the newest toolset (14.44), so this script adds the 14.38
# side-by-side toolset to the installed Visual Studio when it is missing. Then
# it sets CMAKE_GENERATOR_TOOLSET for the next steps of the job. CMake reads
# that variable when CMAKE_GENERATOR is set (the build jobs set it).

param(
    [string]$Version = "14.38",
    [string]$Component = "Microsoft.VisualStudio.Component.VC.14.38.17.8.x86.x64"
)

$ErrorActionPreference = "Stop"

$installerDir = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer"
$vs = & (Join-Path $installerDir "vswhere.exe") -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "No Visual Studio with the C++ tools is installed" }

function Find-Toolset {
    Get-ChildItem (Join-Path $vs "VC\Tools\MSVC") -Directory -Filter "$Version.*" -ErrorAction SilentlyContinue |
        Sort-Object Name | Select-Object -Last 1
}

$toolset = Find-Toolset
# The installer usually takes about 5 minutes, but it can hang without output.
# Give each try 20 minutes, then stop the installer and try once more.
for ($try = 1; -not $toolset -and $try -le 2; $try++) {
    Write-Host "Installing $Component into $vs (try $try)"
    $arguments = @("modify", "--installPath", "`"$vs`"", "--add", $Component, "--quiet", "--norestart", "--nocache")
    $job = Start-Job -ScriptBlock {
        param($exe, $arguments)
        (Start-Process -FilePath $exe -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden).ExitCode
    } -ArgumentList (Join-Path $installerDir "vs_installer.exe"), $arguments
    if (Wait-Job $job -Timeout 1200) {
        $exitCode = Receive-Job $job
        # 3010 means success, a restart is recommended.
        Write-Host "Visual Studio Installer exit code: $exitCode"
    } else {
        Write-Host "Visual Studio Installer did not finish in 20 minutes. Stopping it."
        Stop-Job $job
        Get-Process vs_installer, vs_installershell, setup -ErrorAction SilentlyContinue | Stop-Process -Force
    }
    Remove-Job $job -Force
    $toolset = Find-Toolset
}
if (-not $toolset) { throw "The MSVC $Version toolset is still missing after the install" }

"CMAKE_GENERATOR_TOOLSET=v143,version=$($toolset.Name)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
$cl = Join-Path $toolset.FullName "bin\Hostx64\x64\cl.exe"
Write-Host "Selected MSVC toolset $($toolset.Name): $cl"
# cl.exe without arguments writes its version banner and exits with an error code.
& $cl 2>&1 | Select-Object -First 1 | ForEach-Object { Write-Host "$_" }
exit 0
