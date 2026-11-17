# Build with build-exe.ps1 (it runs: .build-python\python.exe -m PyInstaller --noconfirm CodeStep.spec).
# .build-python is the official python.org Python 3.12.10 prepared by setup-build-python.ps1.
from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / "desktop.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "data" / "curriculum.json"), "data"),
        (str(project / "assets" / "codestep.ico"), "assets"),
        (str(project / "assets" / "codestep_32.png"), "assets"),
        (str(project / "assets" / "codestep_48.png"), "assets"),
        (str(project / "assets" / "codestep_64.png"), "assets"),
        (str(project / "assets" / "codestep_256.png"), "assets"),
        (str(project / "THIRD_PARTY_LICENSES.txt"), "."),
        (str(project / "runner.py"), "."),
    ],
    hiddenimports=["tkinter", "_tkinter", "math", "csv", "statistics", "decimal", "fractions", "random", "json", "datetime", "pathlib", "re", "collections", "itertools", "functools", "string"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["webbrowser", "http.server", "server"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="CodeStep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project / "assets" / "codestep.ico"),
    version=str(project / "assets" / "version_info.txt"),
)
