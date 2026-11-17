"""Direct, local subprocess execution for the native desktop application."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent
RUN_SLOTS = threading.BoundedSemaphore(2)


def run_code(code, stdin=""):
    if not isinstance(code, str) or not isinstance(stdin, str):
        return {"ok": False, "error": "코드와 입력값은 문자열이어야 해요.", "output": ""}
    if len(code) > 8000 or len(stdin) > 4000:
        return {"ok": False, "error": "코드는 8,000자, 입력값은 4,000자까지 사용할 수 있어요.", "output": ""}
    if not code.strip():
        return {"ok": False, "error": "파이썬 코드를 먼저 입력해 주세요.", "output": ""}
    if not RUN_SLOTS.acquire(blocking=False):
        return {"ok": False, "error": "다른 코드를 실행 중이에요. 잠시 후 다시 실행해 주세요.", "output": ""}
    started = time.perf_counter()
    try:
        if getattr(sys, "frozen", False):
            with tempfile.TemporaryDirectory(prefix="codestep-code-") as folder:
                request = Path(folder) / "request.json"
                response = Path(folder) / "response.json"
                request.write_text(json.dumps({"code": code, "stdin": stdin}, ensure_ascii=True), encoding="utf-8")
                environment = os.environ.copy()
                environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
                subprocess.run([sys.executable, "--worker", str(request), str(response)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5, cwd=ROOT, env=environment,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                output = response.read_text(encoding="utf-8") if response.exists() else ""
        else:
            process = subprocess.run([sys.executable, "-I", "-S", str(ROOT / "runner.py")],
                                     input=json.dumps({"code": code, "stdin": stdin}, ensure_ascii=True),
                                     encoding="utf-8", capture_output=True, timeout=5, cwd=ROOT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            output = process.stdout
        try:
            result = json.loads(output)
        except (ValueError, TypeError):
            result = {"ok": False, "output": "", "error": "실행 메모리 한도를 넘었어요. 숫자나 반복 횟수를 줄여 주세요."}
    except subprocess.TimeoutExpired:
        result = {"ok": False, "output": "", "error": "실행 시간이 5초를 넘었어요. 반복문의 종료 조건을 확인해 주세요."}
    except OSError:
        result = {"ok": False, "output": "", "error": "코드 실행기를 시작하지 못했어요. 프로그램을 다시 실행해 주세요."}
    finally:
        RUN_SLOTS.release()
    result["elapsed"] = round((time.perf_counter() - started) * 1000)
    return result


def _run_real_worker_payload(payload, workspace, python_path=None, timeout=5):
    """Run a workspace or interactive Python payload in an isolated worker process."""
    if not RUN_SLOTS.acquire(blocking=False):
        return {"ok": False, "error": "다른 코드를 실행 중이에요. 잠시 후 다시 실행해 주세요.", "output": "", "functionResults": []}

    started = time.perf_counter()
    used_system = bool(python_path and Path(python_path).is_file())
    try:
        with tempfile.TemporaryDirectory(prefix="codestep-ws-") as folder:
            request = Path(folder) / "request.json"
            response = Path(folder) / "response.json"
            request.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

            runner_file = ROOT / "runner.py"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if runner_file.is_file():
                # Python puts a script's own folder first on sys.path. Inside the EXE, runner.py sits next
                # to the bundled Python 3.12 extension modules (_ctypes.pyd, ...), so a PC's Python 3.13+
                # would import those and fail. Run a copy from this run's private folder instead; it also
                # keeps the app's own modules (learning.py, ...) out of reach of the learner's imports.
                private_runner = Path(folder) / "codestep_runner.py"
                shutil.copyfile(runner_file, private_runner)
                runner_file = private_runner
            if used_system and runner_file.is_file():
                environment = os.environ.copy()
                for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "PYINSTALLER_RESET_ENVIRONMENT"):
                    environment.pop(key, None)
                environment["PYTHONUTF8"] = "1"
                environment["PYTHONIOENCODING"] = "utf-8"
                command = [str(python_path), "-X", "utf8", str(runner_file), "--workspace", str(request), str(response)]
                process = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=timeout, cwd=str(workspace),
                                         env=environment, creationflags=flags)
            elif getattr(sys, "frozen", False):
                environment = os.environ.copy()
                environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
                command = [sys.executable, "--real-worker", str(request), str(response)]
                process = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=timeout, cwd=str(workspace),
                                         env=environment, creationflags=flags)
            else:
                command = [sys.executable, "-X", "utf8", str(runner_file), "--workspace", str(request), str(response)]
                process = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=timeout, cwd=str(workspace),
                                         creationflags=flags)

            raw = response.read_text(encoding="utf-8") if response.exists() else ""
            try:
                result = json.loads(raw)
            except (ValueError, TypeError):
                stderr_hint = (process.stderr or "").strip().splitlines()[-1:] or []
                detail = f" ({stderr_hint[0]})" if stderr_hint else ""
                result = {"ok": False, "output": "", "error": f"코드 실행 결과를 받지 못했어요. 메모리 초과이거나 실행기가 비정상 종료됐어요.{detail}", "functionResults": []}
    except subprocess.TimeoutExpired:
        result = {"ok": False, "output": "", "error": f"실행 시간이 {timeout}초를 넘었어요. 반복문의 종료 조건을 확인해 주세요.", "functionResults": []}
    except OSError:
        result = {"ok": False, "output": "", "error": "파이썬 실행기를 시작하지 못했어요. 설정에서 Python 경로를 확인해 주세요.", "functionResults": []}
    finally:
        RUN_SLOTS.release()
    result["elapsed"] = round((time.perf_counter() - started) * 1000)
    result["usedSystemPython"] = used_system
    return result


def run_workspace_script(script_path, work_dir, stdin="", python_path=None, function_checks=None, timeout=5):
    """Execute a real .py workspace file using system Python or embedded Python fallback."""
    script = Path(script_path).resolve()
    workspace = Path(work_dir).resolve()
    if not isinstance(stdin, str):
        return {"ok": False, "error": "입력값은 문자열이어야 해요.", "output": "", "functionResults": []}
    if len(stdin) > 4000:
        return {"ok": False, "error": "입력값은 4,000자까지 사용할 수 있어요.", "output": "", "functionResults": []}
    if not script.is_file():
        return {"ok": False, "error": "실습용 파이썬 파일이 아직 없어요.", "output": "", "functionResults": []}
    try:
        content = script.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = script.read_text(encoding="cp949")
        except OSError:
            return {"ok": False, "error": "파이썬 파일을 읽지 못했어요.", "output": "", "functionResults": []}
    except OSError:
        return {"ok": False, "error": "파이썬 파일을 읽지 못했어요.", "output": "", "functionResults": []}
    if len(content) > 32000:
        return {"ok": False, "error": "파일 크기가 너무 커요(최대 32,000자).", "output": "", "functionResults": []}
    if not content.strip():
        return {"ok": False, "error": "파이썬 코드가 비어 있어요. 코드를 작성한 뒤 저장해 주세요.", "output": "", "functionResults": []}

    payload = {
        "mode": "script",
        "script_path": str(script),
        "work_dir": str(workspace),
        "stdin": stdin,
        "function_checks": function_checks or [],
    }
    return _run_real_worker_payload(payload, workspace, python_path=python_path, timeout=timeout)


def run_repl_command(code, work_dir, history=None, python_path=None, timeout=5):
    """Execute a single >>> interactive Python line against the workspace directory."""
    if not isinstance(code, str) or not code.strip():
        return {"ok": True, "output": "", "error": "", "committed": False, "elapsed": 0, "usedSystemPython": False}
    if len(code) > 4000:
        return {"ok": False, "output": "", "error": "한 번에 입력할 수 있는 명령 길이를 넘었어요.", "committed": False, "elapsed": 0}
    workspace = Path(work_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "repl",
        "code": code,
        "work_dir": str(workspace),
        "history": list(history or [])[-80:],
    }
    return _run_real_worker_payload(payload, workspace, python_path=python_path, timeout=timeout)
