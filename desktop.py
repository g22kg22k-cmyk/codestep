"""Native Windows desktop entry point and isolated Python worker."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def configure_tk():
    # Tcl/Tk is found next to the interpreter: PyInstaller's hook sets it up inside the EXE, and
    # the official Python in .build-python carries its own tcl folder for source runs.
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CodeStep.Desktop.3")


def main():
    # The frozen code worker never initializes another application window.
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        from runner import file_worker
        return file_worker(sys.argv[2], sys.argv[3])
    if len(sys.argv) == 4 and sys.argv[1] == "--real-worker":
        from runner import real_file_worker
        return real_file_worker(sys.argv[2], sys.argv[3])

    import argparse
    parser = argparse.ArgumentParser(description="코드스텝 — Python · Rust 멀티 언어 코딩 학습 데스크톱")
    parser.add_argument("--data-dir", type=Path, help="학습 기록을 보관할 로컬 폴더")
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--auto-exit", type=float, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    configure_tk()
    if args.self_test:
        from native_selftest import run_checks
        return run_checks(args.self_test, args.data_dir)
    from native_app import CodeStepApp
    app = CodeStepApp(data_dir=args.data_dir)
    if args.auto_exit > 0:
        app.after(round(args.auto_exit * 1000), app.close)
    app.mainloop()
    return 0


def show_error(message):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "코드스텝", 0x10)
    elif sys.stderr:
        print(message, file=sys.stderr)


def write_crash_log(detail):
    """Keep the full traceback in a file; the windowed EXE has no console to show it."""
    for folder in (Path(os.environ.get("LOCALAPPDATA", "")) / "CodeStep", Path(os.environ.get("TEMP", ""))):
        try:
            if not str(folder) or str(folder) == ".":
                continue
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / "codestep-error.log"
            target.write_text(detail, encoding="utf-8")
            return target
        except OSError:
            continue
    return None


def describe_startup_error(error, log_path):
    if isinstance(error, PermissionError):
        fix = "학습 기록 폴더에 쓸 권한이 없어요. 백신의 '랜섬웨어 방지(제어된 폴더 액세스)'에서 코드스텝을 허용하거나, 다른 폴더에 복사해 실행해 주세요."
    elif isinstance(error, OSError):
        fix = "파일이나 폴더를 읽고 쓰지 못했어요. 디스크 여유 공간과 폴더 권한을 확인한 뒤 다시 실행해 주세요."
    elif type(error).__name__ == "TclError":
        fix = "화면(Tk)을 만들지 못했어요. 프로그램 파일이 손상됐을 수 있으니 코드스텝.exe를 다시 복사해 실행해 주세요."
    elif isinstance(error, (ValueError, KeyError)):
        fix = "프로그램에 들어 있는 학습 자료를 읽지 못했어요. 코드스텝.exe를 다시 복사해 실행해 주세요."
    else:
        fix = "프로그램을 다시 실행해 보고, 계속되면 아래 기록 파일을 만든 사람에게 보내 주세요."
    lines = ["앱을 시작하지 못했어요.", "", f"원인: {type(error).__name__}: {error}", "", f"해결 방법: {fix}"]
    if log_path:
        lines += ["", f"자세한 기록: {log_path}"]
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        import traceback
        detail = traceback.format_exc()
        background = any(flag in sys.argv for flag in ("--worker", "--real-worker", "--self-test"))
        if not background:
            show_error(describe_startup_error(error, write_crash_log(detail)))
        if sys.stderr:
            print(detail, file=sys.stderr)
        raise SystemExit(1)
