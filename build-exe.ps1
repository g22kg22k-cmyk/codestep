$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.build-python\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.build-python\codestep-build-python.ok'))) {
    throw 'The build Python is not ready. Run setup-build-python.ps1 once first: it unpacks the official Python 3.12.10 from python.org into .build-python. See README.md.'
}
& $buildPython -I -m PyInstaller --noconfirm --distpath (Join-Path $PSScriptRoot 'dist') --workpath (Join-Path $PSScriptRoot 'build') (Join-Path $PSScriptRoot 'CodeStep.spec')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$visibleExe = Join-Path $PSScriptRoot (([string][char]0xCF54) + ([char]0xB4DC) + ([char]0xC2A4) + ([char]0xD15D) + '.exe')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dist\CodeStep.exe') -Destination $visibleExe -Force
$legacyExe = Join-Path $PSScriptRoot (([string][char]0xD30C) + ([char]0xC774) + ([char]0xC2A4) + ([char]0xD15D) + '.exe')
if (Test-Path -LiteralPath $legacyExe) { Remove-Item -LiteralPath $legacyExe -Force }
Write-Host "Ready: $visibleExe"
