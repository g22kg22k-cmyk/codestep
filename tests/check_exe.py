"""Test the native single-file EXE from an isolated folder with no Python on PATH.

It runs twice: once as on a beginner's PC with no Python at all (the EXE's built-in runner),
and once allowing a Python that is installed and registered on this PC (IDLE / terminal linking).
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

MODES = [
    ("no Python installed (built-in runner)", "native-exe-report.json", {"CODESTEP_FORCE_EMBEDDED_PYTHON": "1"}),
    ("installed Python allowed", "native-exe-report-installed-python.json", {}),
]


def run_mode(executable, results, title, report_name, extra_env):
    report = results / report_name
    if report.exists():
        report.unlink()
    environment = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "CODESTEP_FORCE_EMBEDDED_PYTHON"):
        environment.pop(key, None)
    environment["PATH"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    environment.update(extra_env)
    print(f"== {title}", flush=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="native-portable-", dir=results) as folder:
        copy = Path(folder) / "CodeStep.exe"
        shutil.copy2(executable, copy)
        assert list(Path(folder).iterdir()) == [copy]
        process = subprocess.run([str(copy), "--self-test", str(report)], cwd=folder,
                                 env=environment, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=480)
        assert report.exists(), f"Native EXE did not create a report; exit={process.returncode}"
        result = json.loads(report.read_text(encoding="utf-8"))
        assert process.returncode == 0 and result["ok"] and result["frozen"], result
        runtime = result.get("pythonRuntime", "")
        if extra_env.get("CODESTEP_FORCE_EMBEDDED_PYTHON"):
            assert "내장" in runtime, f"expected the built-in runner, got {runtime!r}"
        print(f"     Python used for learner code: {runtime}", flush=True)
        result.update(single_file=True, python_on_path=False, adjacent_assets=False, mode=title)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        for item in result["checks"]:
            print("PASS: " + item, flush=True)
    print(f"PASS: {title} ({time.monotonic() - started:.0f}s). Report: test-results/{report_name}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    results = Path(__file__).resolve().parents[1] / "test-results"
    results.mkdir(exist_ok=True)
    for title, report_name, extra_env in MODES:
        run_mode(args.executable.resolve(), results, title, report_name, extra_env)
    print("PASS: Single EXE, no Python on PATH required.")


if __name__ == "__main__":
    main()
