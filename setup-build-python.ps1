# Prepares .build-python: the official python.org Python 3.12.10, used only to rebuild the EXE
# and to run the source code. Nothing is installed on the system: the four official packages
# are unpacked into this folder (no registry entries, no PATH change), so the folder can be
# moved or renamed and keeps working.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath $PSScriptRoot

# 3.12.10 is the newest 3.12 release with Windows binaries; later 3.12 releases are source-only.
$version = '3.12.10'
$packages = [ordered]@{ 'core.msi' = 2048000; 'exe.msi' = 761856; 'lib.msi' = 7458816; 'tcltk.msi' = 3584000 }
$target = Join-Path $PSScriptRoot '.build-python'
$python = Join-Path $target 'python.exe'
$marker = Join-Path $target 'codestep-build-python.ok'

if (-not (Test-Path -LiteralPath $marker)) {
    # A folder without the marker is left over from an interrupted run; never reuse it.
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    $download = Join-Path ([IO.Path]::GetTempPath()) ('codestep-python-' + [guid]::NewGuid())
    New-Item -ItemType Directory $download | Out-Null
    New-Item -ItemType Directory $target | Out-Null
    try {
        $step = 0
        foreach ($name in $packages.Keys) {
            $step += 1
            $file = Join-Path $download $name
            $url = "https://www.python.org/ftp/python/$version/amd64/$name"
            Write-Host "[$step/$($packages.Count)] $name"
            for ($attempt = 1; $attempt -le 3; $attempt++) {
                try {
                    Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing -TimeoutSec 300
                    break
                } catch {
                    if ($_.Exception -is [System.IO.IOException] -or $_.Exception -is [System.UnauthorizedAccessException]) {
                        throw "Could not save $file ($($_.Exception.Message)). Check free disk space and folder permissions."
                    }
                    $status = $null
                    if ($_.Exception.PSObject.Properties['Response'] -and $_.Exception.Response) { $status = $_.Exception.Response.StatusCode }
                    if ($status -and [int]$status -ge 400 -and [int]$status -lt 500) {
                        throw "python.org answered $([int]$status) for $url. The file list may have changed; check https://www.python.org/ftp/python/$version/amd64/."
                    }
                    if ($attempt -eq 3) { throw "Could not download $url after 3 tries ($($_.Exception.Message)). Check the internet connection and run this script again." }
                    Write-Host "    network error, retrying ($attempt/3): $($_.Exception.Message)"
                    Start-Sleep -Seconds (2 * $attempt)
                }
            }
            $size = (Get-Item -LiteralPath $file).Length
            if ($size -ne $packages[$name]) {
                throw "$name is $size bytes but python.org lists $($packages[$name]). The download is incomplete or the file changed; not using it."
            }
            $signature = Get-AuthenticodeSignature -LiteralPath $file
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=Python Software Foundation') {
                throw "$name is not validly signed by the Python Software Foundation (status: $($signature.Status)); not using it."
            }
            Write-Host "    size and signature OK, unpacking"
            $msi = Start-Process msiexec.exe -ArgumentList @('/a', "`"$file`"", '/qn', "TARGETDIR=`"$target`"") -Wait -PassThru
            if ($msi.ExitCode -ne 0) { throw "Unpacking $name failed (msiexec exit code $($msi.ExitCode))." }
        }
        # msiexec /a leaves a copy of each package in the target folder; it is not part of Python.
        Get-ChildItem -LiteralPath $target -Filter '*.msi' | Remove-Item
        & $python -I -c "import sys, tkinter; assert sys.version.startswith('$version'), sys.version; tkinter.Tcl()"
        if ($LASTEXITCODE -ne 0) { throw 'The unpacked Python did not start, or tkinter is missing.' }
    } catch {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
        throw
    } finally {
        Remove-Item -LiteralPath $download -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host 'Installing the build tools from requirements-build.txt (PyPI)'
& $python -I -m ensurepip --default-pip
if ($LASTEXITCODE -ne 0) { throw 'ensurepip failed; delete .build-python and run this script again.' }
& $python -I -m pip install --disable-pip-version-check --no-warn-script-location -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip could not install requirements-build.txt; see the pip message above.' }
Set-Content -LiteralPath $marker -Value "Python $version from python.org, prepared $(Get-Date -Format s)" -Encoding ascii
Write-Host "Ready: $python"
