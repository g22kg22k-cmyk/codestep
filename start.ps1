$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# 1) A Python chosen on purpose, then 2) the official Python unpacked by setup-build-python.ps1:
#    both mean "run the source code" (development).
$sourcePythons = [System.Collections.Generic.List[string]]::new()
if ($env:CODESTEP_PYTHON) { $sourcePythons.Add($env:CODESTEP_PYTHON) }
elseif ($env:PYSTEP_PYTHON) { $sourcePythons.Add($env:PYSTEP_PYTHON) }
$sourcePythons.Add((Join-Path $PSScriptRoot '.build-python\python.exe'))
foreach ($python in $sourcePythons) {
    if (Test-Path -LiteralPath $python -PathType Leaf) {
        & $python (Join-Path $PSScriptRoot 'desktop.py')
        exit $LASTEXITCODE
    }
}

# 3) The ready-made program next to this script: needs nothing installed.
foreach ($name in 'CodeStep.exe', '코드스텝.exe') {
    $program = Join-Path $PSScriptRoot $name
    if (Test-Path -LiteralPath $program -PathType Leaf) {
        Write-Host "코드스텝을 시작해요 ($name)"
        Start-Process -FilePath $program -WorkingDirectory $PSScriptRoot
        exit 0
    }
}

# 4) Any installed Python on PATH. python.exe / py.exe under WindowsApps are only
#    Microsoft Store shortcuts, not Python.
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand -and $pythonCommand.Source -notmatch '\\Microsoft\\WindowsApps\\') {
    & $pythonCommand.Source (Join-Path $PSScriptRoot 'desktop.py')
    exit $LASTEXITCODE
}
$pyCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pyCommand -and $pyCommand.Source -notmatch '\\Microsoft\\WindowsApps\\') {
    & $pyCommand.Source -3 (Join-Path $PSScriptRoot 'desktop.py')
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host '코드스텝을 실행할 방법을 찾지 못했어요.' -ForegroundColor Yellow
Write-Host ''
Write-Host '  원인: 이 폴더에 CodeStep.exe가 없고, 이 PC에 Python도 설치되어 있지 않아요.'
Write-Host '  해결 1 (추천): CodeStep.exe를 이 폴더에 넣고 두 번 클릭하세요. 설치할 것이 없어요.'
Write-Host '               (GitHub의 Releases에서 받거나, build-exe.ps1로 직접 만들 수 있어요)'
Write-Host '  해결 2 (소스로 실행): setup-build-python.ps1을 한 번 실행한 뒤 start.bat을 다시 여세요.'
Write-Host ''
exit 1
