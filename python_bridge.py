"""Bridge between CodeStep and local Python/Rust toolchains, external editors, and workspace deliverables."""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

from code_executor import run_workspace_script
from rust_bridge import (cmd_echo_escape, console_command, discover_rust_runtime, launch_rust_terminal,
                         run_rust_script)

_RUNTIME_CACHE = {}
_EDITOR_CACHE = None

IGNORED_DIRS = {"__pycache__", ".git", ".venv", "venv", "target"}
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".exe", ".pdb", ".obj", ".o", ".dll", ".pyd", ".pyc", ".zip", ".pdf", ".db", ".sqlite"}


def _is_store_stub(path: Path):
    return path.parent.name.lower() == "windowsapps" and path.name.lower() in ("python.exe", "python3.exe", "py.exe")


def _probe_python(executable: Path):
    try:
        if not executable.is_file() or _is_store_stub(executable):
            return None
        probe = (
            "import sys, json, importlib.util; "
            "print(json.dumps({'version': sys.version.split()[0], "
            "'idle': importlib.util.find_spec('idlelib') is not None, "
            "'executable': sys.executable}))"
        )
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "PYINSTALLER_RESET_ENVIRONMENT"):
            env.pop(key, None)
        proc = subprocess.run(
            [str(executable), "-c", probe],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            return None
        info = json.loads(proc.stdout.strip().splitlines()[-1])
        resolved = Path(info["executable"])
        pythonw = resolved.with_name("pythonw.exe")
        return {
            "available": True,
            "mode": "system",
            "path": str(resolved),
            "pythonw": str(pythonw) if pythonw.is_file() else str(resolved),
            "version": str(info.get("version", "")),
            "hasIdle": bool(info.get("idle")),
            "label": f"Python {info.get('version', '')} (시스템 연동)",
        }
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired, IndexError):
        return None


def _candidate_pythons(custom_path=""):
    candidates = []
    seen = set()

    def add(path_like, source):
        if not path_like:
            return
        try:
            p = Path(str(path_like)).expanduser()
            key = str(p).lower()
        except (OSError, ValueError):
            return
        if key not in seen:
            seen.add(key)
            candidates.append((p, source))

    if custom_path:
        add(custom_path, "custom")

    if not getattr(sys, "frozen", False):
        add(sys.executable, "current")

    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            add(found, "path")

    py_launcher = shutil.which("py")
    if py_launcher and not _is_store_stub(Path(py_launcher)):
        try:
            proc = subprocess.run(
                [py_launcher, "-0p"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.strip().split()
                    if parts and parts[-1].lower().endswith(".exe"):
                        add(parts[-1], "py-launcher")
        except (OSError, subprocess.TimeoutExpired):
            pass

    try:
        for exe in order_registered_pythons(_read_pep514_registry()):
            add(exe, "registry")
    except (OSError, ImportError):
        pass
    manager_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Python"
    try:
        if os.environ.get("LOCALAPPDATA") and manager_root.is_dir():
            for item in sorted(manager_root.glob("pythoncore-*"), key=lambda p: _version_key(p.name), reverse=True):
                add(item / "python.exe", "install-manager")
    except OSError:
        pass

    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path("C:/"),
    ]
    for base in roots:
        if not str(base) or not base.is_dir():
            continue
        try:
            for item in sorted(base.glob("Python*"), reverse=True):
                add(item / "python.exe", "installed")
        except OSError:
            pass

    # Python bundled inside other apps (for example under WindowsApps) is deliberately not used:
    # it belongs to that app and can disappear or move whenever the app updates.
    return candidates


def _version_key(text):
    match = re.search(r"(\d+)\.(\d+)", str(text))
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def order_registered_pythons(entries):
    """Newest first; drop the launcher's own key and entries without an executable."""
    usable = [(company, version, exe) for company, version, exe in entries
              if exe and str(company).lower() != "pylauncher"]
    usable.sort(key=lambda item: _version_key(item[1]), reverse=True)
    return [exe for _, _, exe in usable]


def _read_pep514_registry():
    """Yield (company, version, python.exe) for every Python registered the standard Windows way (PEP 514).

    Both the python.org installer and the newer Python install manager (which installs into
    %LOCALAPPDATA%\\Python\\pythoncore-*) register here, so this finds them wherever they live.
    """
    if sys.platform != "win32":
        return []
    import winreg

    def subkeys(key):
        index = 0
        while True:
            try:
                yield winreg.EnumKey(key, index)
            except OSError:
                return
            index += 1

    def value(key, name):
        try:
            return str(winreg.QueryValueEx(key, name)[0] or "")
        except OSError:
            return ""

    found = []
    for hive, view in ((winreg.HKEY_CURRENT_USER, 0),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)):
        access = winreg.KEY_READ | view
        try:
            root = winreg.OpenKey(hive, r"Software\Python", 0, access)
        except OSError:
            continue
        with root:
            for company in list(subkeys(root)):
                try:
                    company_key = winreg.OpenKey(root, company, 0, access)
                except OSError:
                    continue
                with company_key:
                    for tag in list(subkeys(company_key)):
                        try:
                            with winreg.OpenKey(company_key, tag, 0, access) as tag_key:
                                version = value(tag_key, "SysVersion") or tag
                                with winreg.OpenKey(tag_key, "InstallPath", 0, access) as install:
                                    exe = value(install, "ExecutablePath")
                                    folder = value(install, "")
                        except OSError:
                            continue
                        if not exe and folder:
                            exe = str(Path(folder) / "python.exe")
                        found.append((company, version, exe))
    return found


def discover_python_runtime(custom_path="", refresh=False):
    cache_key = str(custom_path or "").strip()
    if not refresh and cache_key in _RUNTIME_CACHE:
        return dict(_RUNTIME_CACHE[cache_key])

    # CODESTEP_FORCE_EMBEDDED_PYTHON=1 behaves like a PC with no Python installed; the EXE check
    # uses it to test the beginner case on a machine that does have Python.
    forced_embedded = os.environ.get("CODESTEP_FORCE_EMBEDDED_PYTHON") == "1"
    for candidate, source in ([] if forced_embedded else _candidate_pythons(cache_key)):
        info = _probe_python(candidate)
        if info:
            info["source"] = source
            _RUNTIME_CACHE[cache_key] = info
            return dict(info)

    embedded_version = sys.version.split()[0]
    fallback = {
        "available": False,
        "mode": "embedded",
        "path": "",
        "pythonw": "",
        "version": embedded_version,
        "hasIdle": False,
        "label": f"Python {embedded_version} (내장 기본 실행기)",
        "source": "embedded",
    }
    _RUNTIME_CACHE[cache_key] = fallback
    return dict(fallback)


def discover_editors(refresh=False):
    global _EDITOR_CACHE
    if _EDITOR_CACHE is not None and not refresh:
        return dict(_EDITOR_CACHE)
    vscode = shutil.which("code") or ""
    if not vscode:
        for path in (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft VS Code" / "Code.exe",
        ):
            try:
                if path.is_file():
                    vscode = str(path)
                    break
            except OSError:
                continue
    _EDITOR_CACHE = {"vscode": vscode}
    return dict(_EDITOR_CACHE)


def read_text_safe(path: Path):
    path = Path(path)
    for attempt in range(2):
        try:
            raw = path.read_bytes()
            for encoding in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        except OSError:
            if attempt == 0:
                time.sleep(0.04)
    return ""


def write_text_safe(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def text_digest(text: str):
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class WorkspaceManager:
    """Manages real .py practice files and workspace fixtures on disk."""

    def __init__(self, store_folder: Path, custom_dir="", isolated=False):
        self.store_folder = Path(store_folder)
        self.isolated = isolated
        self.root = self._resolve_root(custom_dir)

    def _resolve_root(self, custom_dir=""):
        candidates = []
        if custom_dir:
            candidates.append(Path(custom_dir).expanduser())
        if not self.isolated:
            docs = Path.home() / "Documents"
            if docs.is_dir():
                candidates.append(docs / "CodeStep_실습")
            candidates.append(Path.home() / "CodeStep_실습")
        candidates.append(self.store_folder / "workspace")
        for folder in candidates:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                probe = folder / ".codestep_write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return folder
            except OSError:
                continue
        fallback = self.store_folder / "workspace"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def set_custom_dir(self, custom_dir=""):
        self.root = self._resolve_root(custom_dir)
        return self.root

    def task_dir(self, question_id: str):
        safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in question_id)
        return self.root / "lessons" / safe_id

    def playground_dir(self):
        return self.root / "playground"

    def prepare_workspace(self, target_dir: Path, script_name: str, starter_code: str, fixtures=None, reset_code=False):
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        fixtures = fixtures or {}
        for filename, content in fixtures.items():
            file_path = (target_dir / filename).resolve()
            if file_path.is_relative_to(target_dir.resolve()):
                if reset_code or not file_path.exists():
                    write_text_safe(file_path, content)
        script_path = target_dir / script_name
        if reset_code or not script_path.exists():
            write_text_safe(script_path, starter_code)
        return target_dir, script_path, read_text_safe(script_path)

    @staticmethod
    def ensure_fixtures(target_dir: Path, fixtures=None):
        target_dir = Path(target_dir)
        for filename, content in (fixtures or {}).items():
            file_path = (target_dir / filename).resolve()
            if file_path.is_relative_to(target_dir.resolve()) and not file_path.exists():
                write_text_safe(file_path, content)


def scan_deliverables(target_dir: Path, script_name="main.py", fixtures=None):
    """Inspect created/modified deliverable files in a task workspace directory."""
    target_dir = Path(target_dir)
    fixtures = fixtures or {}
    items = []
    if not target_dir.is_dir():
        return items
    try:
        entries = sorted(target_dir.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    except OSError:
        return items
    ignore_names = {script_name}
    if script_name.startswith("practice."):
        ignore_names.update({"practice.py", "practice.rs", "practice.exe", "practice.pdb"})
    for entry in entries:
        if entry.name in IGNORED_DIRS or entry.name in ignore_names or entry.name.startswith("."):
            continue
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        is_fixture = entry.name in fixtures
        preview = ""
        if entry.suffix.lower() in BINARY_EXTENSIONS or stat.st_size > 200_000:
            preview = f"({stat.st_size:,} bytes · 미리보기 생략)"
        else:
            preview = read_text_safe(entry)[:4000]
        changed_fixture = is_fixture and preview != fixtures[entry.name]
        items.append({
            "name": entry.name,
            "path": str(entry),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%H:%M:%S"),
            "kind": "입력 데이터" if (is_fixture and not changed_fixture) else "실기 결과물",
            "isOutput": (not is_fixture) or changed_fixture,
            "preview": preview,
        })
    return items


def launch_idle(script_path: Path, work_dir: Path, runtime: dict):
    if not runtime.get("available") or not runtime.get("hasIdle"):
        return False, "이 PC에서 Python IDLE을 찾지 못했어요. 설정에서 Python 경로를 지정하거나 기본 에디터로 열어 주세요."
    exe = runtime.get("pythonw") or runtime["path"]
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "PYINSTALLER_RESET_ENVIRONMENT"):
        env.pop(key, None)
    try:
        subprocess.Popen([exe, "-m", "idlelib", str(script_path)], cwd=str(work_dir), env=env)
        return True, "Python IDLE에서 실습 파일을 열었어요. 코드를 수정하고 저장(Ctrl+S)하면 자동 인식돼요."
    except OSError as error:
        return False, f"IDLE을 실행하지 못했어요: {error}"


def launch_vscode(script_path: Path, work_dir: Path, vscode_path: str):
    if not vscode_path:
        return False, "VS Code를 찾지 못했어요."
    try:
        subprocess.Popen([vscode_path, str(work_dir), str(script_path)],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True, "VS Code에서 실습 폴더와 파일을 열었어요."
    except OSError as error:
        return False, f"VS Code를 실행하지 못했어요: {error}"


def launch_default_editor(script_path: Path):
    script_path = Path(script_path)
    try:
        if sys.platform == "win32":
            # Avoid running .py directly via shell association if .py opens a transient console; open with notepad/editor fallback safely.
            notepad = shutil.which("notepad.exe") or "notepad.exe"
            subprocess.Popen([notepad, str(script_path)])
            return True, "메모장에서 실습 파일을 열었어요. 저장(Ctrl+S)하면 학습 앱에 반영돼요."
        os.startfile(str(script_path))
        return True, "기본 에디터에서 파일을 열었어요."
    except OSError as error:
        return False, f"편집기를 열지 못했어요: {error}"


def launch_folder(target_dir: Path):
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(target_dir))
        else:
            subprocess.Popen(["xdg-open", str(target_dir)])
        return True, "실습 작업 폴더를 열었어요."
    except OSError as error:
        return False, f"폴더를 열지 못했어요: {error}"


def launch_terminal(script_path: Path, work_dir: Path, runtime: dict):
    if not runtime.get("available"):
        return False, "터미널 실행에는 PC에 설치된 Python이 필요해요. '실행하기' 버튼으로 내장 Python에서 실행할 수 있어요."
    if sys.platform != "win32":
        return False, "터미널 바로 실행은 Windows에서만 지원해요."
    try:
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "PYINSTALLER_RESET_ENVIRONMENT"):
            env.pop(key, None)
        subprocess.Popen(python_terminal_command(script_path, work_dir, runtime), cwd=str(work_dir), env=env,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return True, "실제 Python 터미널 창에서 코드를 실행했어요."
    except OSError as error:
        return False, f"터미널을 열지 못했어요: {error}"


def python_terminal_command(script_path: Path, work_dir: Path, runtime: dict, wait_for_key=True) -> str:
    name = Path(script_path).name
    inner = (
        f'color 07 & chcp 65001>nul & title Python {runtime.get("version", "")} - {name}'
        f' & echo {cmd_echo_escape(work_dir)}^> python -X utf8 "{name}" & echo.'
        f' & "{runtime["path"]}" -X utf8 "{script_path}"'
    )
    return console_command(inner, wait_for_key)


def _evaluate_file_checks(target_dir: Path, file_checks: list):
    results = []
    root = Path(target_dir).resolve()
    for check in file_checks or []:
        rel = check["path"]
        candidate = (root / rel).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            results.append({"label": f"결과 파일: {rel}", "ok": False, "detail": f"'{rel}' 파일이 생성되지 않았어요."})
            continue
        mode = check.get("mode", "text")
        raw_text = read_text_safe(candidate)
        if mode == "json":
            try:
                parsed = json.loads(raw_text)
            except ValueError as error:
                results.append({"label": f"결과 파일: {rel}", "ok": False, "detail": f"JSON 형식이 올바르지 않아요: {error}"})
                continue
            expected_json = check.get("expectedJson")
            if isinstance(expected_json, dict) and isinstance(parsed, dict):
                missing = [f"{k}={v!r}" for k, v in expected_json.items() if parsed.get(k) != v]
                ok = not missing
                detail = "JSON 구조와 값이 일치해요." if ok else f"기대한 값과 달라요: {', '.join(missing)}"
            else:
                ok = parsed == expected_json
                detail = "JSON 내용이 일치해요." if ok else f"기대한 JSON({expected_json!r})과 달라요."
            results.append({"label": f"결과 파일: {rel}", "ok": ok, "detail": detail})
        elif mode == "csv":
            rows = list(csv.reader(io.StringIO(raw_text)))
            min_rows = check.get("minRows", 1)
            ok = len(rows) >= min_rows
            if ok and check.get("contains"):
                for token in check["contains"]:
                    if token not in raw_text:
                        ok = False
                        break
            detail = f"CSV {len(rows)}행 확인됨" if ok else "CSV 행 수나 내용을 확인해 주세요."
            results.append({"label": f"결과 파일: {rel}", "ok": ok, "detail": detail})
        else:
            normalized = raw_text.replace("\r\n", "\n")
            ok = True
            detail = f"'{rel}' 파일 확인됨"
            if "equals" in check:
                target_norm = check["equals"].replace("\r\n", "\n").rstrip("\n")
                actual_norm = normalized.rstrip("\n")
                ok = actual_norm == target_norm
                if not ok:
                    a_prev = actual_norm.splitlines()[0][:40] if actual_norm else "(빈 파일)"
                    t_prev = target_norm.splitlines()[0][:40] if target_norm else ""
                    detail = f"'{rel}'의 내용이 목표와 달라요 (첫 줄: {a_prev} / 목표: {t_prev})."
            for snippet in check.get("contains", []):
                if snippet not in normalized:
                    ok = False
                    detail = f"'{rel}' 안에 '{snippet}' 내용이 포함되어야 해요."
                    break
            results.append({"label": f"결과 파일: {rel}", "ok": ok, "detail": detail})
    return results


def _short(text, limit=40):
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _char_name(ch):
    return {"": "(글자 없음)", " ": "빈칸", "\t": "탭"}.get(ch, f"'{ch}'")


def describe_output_difference(actual: str, target: str) -> str:
    """Tell a beginner exactly where their output first differs from the goal.

    "The output is different" alone is hard to act on: the usual causes are one wrong capital
    letter, a missing comma or space, or a Korean-keyboard full-width symbol that looks the same.
    """
    a_lines, t_lines = actual.split("\n"), target.split("\n")
    compare = f"\n내 출력: {_short(actual.replace(chr(10), ' / '), 48)}\n목표: {_short(target.replace(chr(10), ' / '), 48)}"
    for index in range(max(len(a_lines), len(t_lines))):
        a = a_lines[index] if index < len(a_lines) else None
        t = t_lines[index] if index < len(t_lines) else None
        if a == t:
            continue
        line_no = index + 1
        if a is None:
            return f"출력이 {len(a_lines)}줄에서 끝났어요. 목표는 {len(t_lines)}줄이라 {line_no}번째 줄 '{_short(t)}'이(가) 더 나와야 해요." + compare
        if t is None:
            return f"목표는 {len(t_lines)}줄인데 {len(a_lines)}줄이 출력됐어요. {line_no}번째 줄 '{_short(a)}'은(는) 목표에 없는 출력이에요." + compare
        col = next((i for i, (x, y) in enumerate(zip(a, t)) if x != y), min(len(a), len(t)))
        got, want = a[col:col + 1], t[col:col + 1]
        if not got:
            rest = t[col:]
            what = "빈칸이 빠졌어요" if not rest.strip() else f"'{_short(rest)}' 부분이 빠졌어요"
            return f"{line_no}번째 줄 끝에 {what}." + compare
        if not want:
            rest = a[col:]
            what = "필요 없는 빈칸이 붙어 있어요" if not rest.strip() else f"'{_short(rest)}' 부분이 더 붙어 있어요"
            return f"{line_no}번째 줄 끝에 {what}." + compare
        reason = ""
        if got.lower() == want.lower():
            reason = " 대문자와 소문자는 서로 다른 글자로 봐요."
        elif unicodedata.normalize("NFKC", got) == want:
            reason = " 모양은 비슷하지만 한글 자판의 전각 기호예요. 영문 자판으로 바꿔 다시 입력해 보세요."
        elif " " in (got, want):
            reason = " 띄어쓰기를 확인해 보세요."
        return f"{line_no}번째 줄 {col + 1}번째 글자가 달라요: 내 글자는 {_char_name(got)}, 목표 글자는 {_char_name(want)}.{reason}" + compare
    return "출력 결과가 목표와 달라요. 철자·띄어쓰기·줄바꿈을 확인해 보세요." + compare


def _clean_stale_outputs(target_dir: Path, file_checks: list, fixtures: dict):
    """Remove non-fixture fileChecks targets before execution so deleted file-write logic never passes via stale artifacts."""
    root = target_dir.resolve()
    fixture_names = set((fixtures or {}).keys())
    for chk in file_checks or []:
        rel = chk.get("path", "")
        if not rel or rel in fixture_names:
            continue
        candidate = (target_dir / rel).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            try:
                candidate.unlink()
            except OSError:
                pass


def _copy_workspace_to_temp(source_dir: Path, dest_dir: Path):
    for entry in source_dir.iterdir():
        if entry.name in IGNORED_DIRS or entry.name.startswith("."):
            continue
        if entry.is_file() and entry.stat().st_size <= 2_000_000:
            shutil.copy2(entry, dest_dir / entry.name)


def verify_workspace_question(task_dir: Path, script_path: Path, question: dict, runtime: dict, isolated=False):
    """Run the learner's .py or .rs file and evaluate stdout, functions, and generated files."""
    task_dir = Path(task_dir)
    script_path = Path(script_path)
    fixtures = question.get("fixtures") or {}
    WorkspaceManager.ensure_fixtures(task_dir, fixtures)

    is_rust = (question.get("lang") == "rust") or (script_path.suffix.lower() == ".rs")
    runtime_path = runtime.get("path") if runtime.get("available") else None
    stdin = question.get("stdin", "")
    func_checks = question.get("functionChecks") or []
    file_checks = question.get("fileChecks") or []

    def _run_target(run_dir: Path, run_script: Path):
        if is_rust:
            return run_rust_script(run_script, run_dir, stdin=stdin, rust_path=runtime_path, function_checks=func_checks)
        return run_workspace_script(run_script, run_dir, stdin=stdin, python_path=runtime_path, function_checks=func_checks)

    if isolated:
        with tempfile.TemporaryDirectory(prefix="codestep-verify-") as tmp:
            tmp_dir = Path(tmp)
            _copy_workspace_to_temp(task_dir, tmp_dir)
            WorkspaceManager.ensure_fixtures(tmp_dir, fixtures)
            _clean_stale_outputs(tmp_dir, file_checks, fixtures)
            run_dir = tmp_dir
            run_script = tmp_dir / script_path.name
            exec_res = _run_target(run_dir, run_script)
            file_results = _evaluate_file_checks(run_dir, file_checks) if exec_res.get("ok") else []
            deliverables = scan_deliverables(run_dir, script_name=script_path.name, fixtures=fixtures)
    else:
        _clean_stale_outputs(task_dir, file_checks, fixtures)
        exec_res = _run_target(task_dir, script_path)
        file_results = _evaluate_file_checks(task_dir, file_checks) if exec_res.get("ok") else []
        deliverables = scan_deliverables(task_dir, script_name=script_path.name, fixtures=fixtures)

    checks = []
    run_label = "Rust 컴파일 및 실행" if is_rust else "코드 문법 및 실행"
    if exec_res.get("ok"):
        checks.append({"label": run_label, "ok": True, "detail": f"{exec_res.get('elapsed', 0)} ms 완료"})
    else:
        checks.append({"label": run_label, "ok": False, "detail": exec_res.get("error", "실행 오류")})

    expected_out = question.get("expected")
    if expected_out:
        actual_out = exec_res.get("output", "").replace("\r\n", "\n").rstrip("\n")
        target_out = expected_out.replace("\r\n", "\n").rstrip("\n")
        out_ok = bool(exec_res.get("ok") and actual_out == target_out)
        if out_ok:
            out_detail = "목표 출력과 일치해요."
        elif not exec_res.get("ok"):
            out_detail = "먼저 컴파일/실행 오류를 해결한 뒤 출력을 다시 확인해 주세요." if is_rust else "먼저 코드 실행 오류를 해결한 뒤 출력을 다시 확인해 주세요."
        elif not actual_out.strip():
            out_hint = "println!(...)" if is_rust else "print(...)"
            out_detail = f"화면에 출력된 내용이 없어요. {out_hint}가 실행되었는지 확인해 보세요."
        else:
            out_detail = describe_output_difference(actual_out, target_out)
        checks.append({
            "label": "화면 출력 결과(stdout)",
            "ok": out_ok,
            "detail": out_detail,
        })

    for fn_res in exec_res.get("functionResults", []):
        checks.append({"label": f"함수 검증: {fn_res['name']}()", "ok": bool(fn_res["ok"]), "detail": fn_res["detail"]})

    checks.extend(file_results)

    passed = bool(exec_res.get("ok") and all(item["ok"] for item in checks))
    if passed:
        summary = question.get("explanation", "완벽해요! 코드와 실기 결과물이 모두 확인되었어요.")
    elif not exec_res.get("ok"):
        summary = (
            "컴파일 또는 실행 오류가 발생했어요. 오른쪽 터미널과 아래 안내를 확인해 고쳐 보세요."
            if not exec_res.get("missingCompiler")
            else "Rust 컴파일러(rustc) 설치가 필요해요. 준비 탭에서 설치한 뒤 다시 채점해 보세요."
        )
    else:
        failed = next((item for item in checks if not item["ok"]), None)
        summary = failed["detail"] if failed else exec_res.get("error", "실행 결과를 다시 확인해 주세요.")

    runtime_mode = ("rustc" if runtime.get("available") else "missing-rustc") if is_rust else (
        "system" if exec_res.get("usedSystemPython") else "embedded"
    )
    return {
        "ok": bool(exec_res.get("ok")),
        "passed": passed,
        "missingCompiler": bool(exec_res.get("missingCompiler")),
        "output": exec_res.get("output", ""),
        "error": exec_res.get("error", ""),
        "line": exec_res.get("line"),
        "elapsed": exec_res.get("elapsed", 0),
        "runtimeMode": runtime_mode,
        "runtimeLabel": runtime.get("label", ""),
        "checks": checks,
        "deliverables": deliverables,
        "summary": summary,
    }


def _ps_quote(value: str):
    return "'" + str(value or "").replace("'", "''") + "'"


def _safe_is_file(path: Path):
    try:
        return path.is_file()
    except OSError:
        return False


def discover_msvc_linker():
    """Return path to Visual Studio MSVC link.exe if installed on Windows."""
    roots = []
    for env_var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env_var, "")
        if base:
            roots.append(Path(base) / "Microsoft Visual Studio")
    for vs_root in roots:
        try:
            if not vs_root.is_dir():
                continue
            for rel_pat in (
                "*/*/VC/Tools/MSVC/*/bin/Hostx64/x64/link.exe",
                "*/*/VC/Tools/MSVC/*/bin/Hostx86/x64/link.exe",
                "*/*/VC/Tools/MSVC/*/bin/Hostx86/x86/link.exe",
            ):
                matches = sorted(vs_root.glob(rel_pat), reverse=True)
                for candidate in matches:
                    if _safe_is_file(candidate):
                        return str(candidate)
        except OSError:
            continue
    on_path = shutil.which("link.exe") or ""
    lowered = on_path.lower()
    if on_path and ("vc\\tools\\msvc" in lowered or "microsoft visual studio" in lowered):
        return on_path
    return ""


def discover_vscode_cli_and_extensions(vscode_path="", home_dir=None):
    """Find code.cmd CLI path and inspect whether key VS Code extensions are installed."""
    code_cli = ""
    if vscode_path:
        try:
            vsp = Path(vscode_path)
            if vsp.name.lower() == "code.exe":
                cand = vsp.parent / "bin" / "code.cmd"
                if _safe_is_file(cand):
                    code_cli = str(cand)
            elif vsp.suffix.lower() in (".cmd", ".bat", ".exe") and _safe_is_file(vsp):
                code_cli = str(vsp)
        except OSError:
            pass
    if not code_cli:
        code_cli = shutil.which("code.cmd") or shutil.which("code") or ""

    ext_dir = (Path(home_dir) if home_dir else Path.home()) / ".vscode" / "extensions"
    py_ext = False
    rust_ext = False
    try:
        if ext_dir.is_dir():
            for item in ext_dir.iterdir():
                name = item.name.lower()
                if name.startswith("ms-python.python-"):
                    py_ext = True
                elif name.startswith("rust-lang.rust-analyzer-"):
                    rust_ext = True
    except OSError:
        py_ext = None
        rust_ext = None

    return {"codeCli": code_cli, "pyExt": py_ext, "rustExt": rust_ext}


def discover_setup_status(
    python_runtime=None,
    rust_runtime=None,
    editors=None,
    custom_python="",
    custom_rust="",
    refresh=False,
    home_dir=None,
):
    """Collect installed status of Python, Rust, MSVC Build Tools, VS Code, and extensions."""
    py_rt = dict(python_runtime) if python_runtime is not None and not refresh else discover_python_runtime(custom_python, refresh=refresh)
    rs_rt = dict(rust_runtime) if rust_runtime is not None and not refresh else discover_rust_runtime(custom_rust, refresh=refresh)
    ed_info = dict(editors) if editors is not None and not refresh else discover_editors(refresh=refresh)

    winget = shutil.which("winget") or ""
    if not winget:
        cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "winget.exe"
        if _safe_is_file(cand):
            winget = str(cand)

    msvc = discover_msvc_linker()
    vsc_extra = discover_vscode_cli_and_extensions(ed_info.get("vscode", ""), home_dir=home_dir)
    return {
        "python": py_rt,
        "rust": rs_rt,
        "editors": ed_info,
        "winget": winget,
        "msvc": msvc,
        "codeCli": vsc_extra["codeCli"],
        "pyExt": vsc_extra["pyExt"],
        "rustExt": vsc_extra["rustExt"],
    }


def get_setup_catalog(status: dict):
    """Return structured setup items (with Korean descriptions and install steps) per language."""
    py_rt = status.get("python") or {}
    rs_rt = status.get("rust") or {}
    ed_info = status.get("editors") or {}
    has_vscode = bool(ed_info.get("vscode") or status.get("codeCli"))
    py_ext = status.get("pyExt")
    rust_ext = status.get("rustExt")
    msvc = status.get("msvc", "")

    def ext_status(val):
        if val is True:
            return "설치됨"
        if val is None:
            return "자동 확인 제한 (VS Code에서 확인 또는 버튼으로 설치)"
        return "미설치 (VS Code 설치 후 추가)" if not has_vscode else "미설치"

    vscode_cmd = "winget install -e --id Microsoft.VisualStudioCode"
    msvc_override = "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    msvc_cmd = f'winget install -e --id Microsoft.VisualStudio.2022.BuildTools --override "{msvc_override}"'

    return {
        "python": [
            {
                "id": "python3",
                "title": "Python 3.12 (공식 실행기 · IDLE 포함)",
                "badge": "권장 · 외부/IDLE 연동",
                "required": False,
                "installed": bool(py_rt.get("available")),
                "statusText": (
                    f"설치됨 · Python {py_rt.get('version', '')}" + (" (IDLE 포함)" if py_rt.get("hasIdle") else "")
                    if py_rt.get("available")
                    else "미설치 · 현재 코드스텝 내장 Python으로 동작 중"
                ),
                "detail": (
                    "코드스텝은 Python을 내장하고 있어 지금도 학습할 수 있지만, 공식 Python 3을 설치하면 "
                    "Python IDLE 편집기, Windows 터미널 직접 실행, 외부 프로젝트 실습까지 연동할 수 있어요."
                ),
                "command": "winget install -e --id Python.Python.3.12",
                "step": {
                    "kind": "winget",
                    "label": "Python 3.12 (공식 실행기 + IDLE)",
                    "packageId": "Python.Python.3.12",
                    "displayCmd": "winget install -e --id Python.Python.3.12",
                },
            },
            {
                "id": "vscode",
                "title": "Visual Studio Code (코드 에디터)",
                "badge": "권장 · 코드 편집기",
                "required": False,
                "installed": has_vscode,
                "statusText": "설치됨 · VS Code 연동 가능" if has_vscode else "미설치",
                "detail": (
                    "실습 중 'VS Code로 열기' 버튼을 누르면 전문 편집기에서 자동 완성·문법 색상을 보며 코딩하고, "
                    "저장(Ctrl+S)할 때마다 코드스텝이 변경 내용을 즉시 채점해 줍니다."
                ),
                "command": vscode_cmd,
                "step": {
                    "kind": "winget",
                    "label": "Visual Studio Code",
                    "packageId": "Microsoft.VisualStudioCode",
                    "displayCmd": vscode_cmd,
                },
            },
            {
                "id": "vscode-python",
                "title": "VS Code Python 확장 (ms-python.python)",
                "badge": "VS Code 확장",
                "required": False,
                "requiresVscode": True,
                "installed": py_ext,
                "statusText": ext_status(py_ext),
                "detail": (
                    "VS Code가 .py 파일을 이해하고 실시간 문법 오류 표시, 자동 완성, 실행(▶) 버튼을 제공하도록 해 주는 "
                    "Microsoft 공식 Python 확장입니다. (VS Code 설치 후 실행)"
                ),
                "command": "code --install-extension ms-python.python",
                "step": {
                    "kind": "vscode-ext",
                    "label": "VS Code Python 확장 (ms-python.python)",
                    "extId": "ms-python.python",
                    "displayCmd": "code --install-extension ms-python.python",
                },
            },
        ],
        "rust": [
            {
                "id": "msvc-buildtools",
                "title": "Visual Studio Build Tools 2022 (MSVC C++ 링커)",
                "badge": "필수 · Windows 링커",
                "required": True,
                "installed": bool(msvc),
                "statusText": "설치됨 · MSVC link.exe 감지됨" if msvc else "미설치 · rustup 설치 전에 먼저 설치 권장",
                "detail": (
                    "Windows에서 rustc가 실행 파일(.exe)을 만들 때 Microsoft C++ 링커(link.exe)와 Windows SDK가 필요합니다. "
                    "이 도구를 먼저 설치해 두면 뒤이어 Rust를 설치할 때 C++ 경고 없이 곧바로 설치돼요."
                ),
                "command": msvc_cmd,
                "step": {
                    "kind": "winget",
                    "label": "Visual Studio Build Tools 2022 (C++ 링커)",
                    "packageId": "Microsoft.VisualStudio.2022.BuildTools",
                    "override": msvc_override,
                    "displayCmd": msvc_cmd,
                },
            },
            {
                "id": "rustup",
                "title": "Rust 도구 모음 (rustup · rustc · cargo)",
                "badge": "필수 · Rust 컴파일러",
                "required": True,
                "installed": bool(rs_rt.get("available")),
                "statusText": (
                    f"설치됨 · rustc {rs_rt.get('version', '')}" + (" (cargo 포함)" if rs_rt.get("cargo") else "")
                    if rs_rt.get("available")
                    else "미설치 · Rust 코드 실행을 위해 설치 필요"
                ),
                "detail": (
                    "Rust 설치 관리자(rustup), 컴파일러(rustc), 패키지·빌드 도구(cargo)를 한 번에 설치합니다. "
                    "터미널에서 선택 화면이 나오면 Enter(기본 1번)를 눌러 진행하면 됩니다."
                ),
                "command": "winget install -e --id Rustlang.Rustup",
                "step": {
                    "kind": "winget",
                    "label": "Rust 도구 모음 (rustup · rustc · cargo)",
                    "packageId": "Rustlang.Rustup",
                    "displayCmd": "winget install -e --id Rustlang.Rustup",
                },
            },
            {
                "id": "vscode",
                "title": "Visual Studio Code (코드 에디터)",
                "badge": "권장 · 코드 편집기",
                "required": False,
                "installed": has_vscode,
                "statusText": "설치됨 · VS Code 연동 가능" if has_vscode else "미설치",
                "detail": (
                    "코드스텝에서 'VS Code로 열기'를 누르면 main.rs 파일이 열리며, 저장(Ctrl+S)할 때마다 "
                    "코드스텝이 자동으로 Rust 컴파일 및 채점 결과를 보여 줍니다."
                ),
                "command": vscode_cmd,
                "step": {
                    "kind": "winget",
                    "label": "Visual Studio Code",
                    "packageId": "Microsoft.VisualStudioCode",
                    "displayCmd": vscode_cmd,
                },
            },
            {
                "id": "vscode-rust-analyzer",
                "title": "rust-analyzer 확장 (VS Code Rust 지원)",
                "badge": "VS Code 확장",
                "required": False,
                "requiresVscode": True,
                "installed": rust_ext,
                "statusText": ext_status(rust_ext),
                "detail": (
                    "VS Code 안에서 변수의 추정 타입 힌트, 소유권·빌림 오류 실시간 밑줄, 함수 정의 이동을 지원하는 "
                    "공식 Rust 언어 확장입니다. (VS Code 설치 후 실행)"
                ),
                "command": "code --install-extension rust-lang.rust-analyzer",
                "step": {
                    "kind": "vscode-ext",
                    "label": "VS Code rust-analyzer 확장",
                    "extId": "rust-lang.rust-analyzer",
                    "displayCmd": "code --install-extension rust-lang.rust-analyzer",
                },
            },
        ],
    }


def build_installer_ps1(steps: list, title: str = "코드스텝 개발 환경 설치", code_cli: str = ""):
    """Build a UTF-8 PowerShell script that runs winget / VS Code extension installs interactively."""
    lines = [
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        f"$Host.UI.RawUI.WindowTitle = {_ps_quote(title)}",
        "Write-Host '==================================================' -ForegroundColor Cyan",
        f"Write-Host {_ps_quote('  ' + title)} -ForegroundColor Cyan",
        "Write-Host '==================================================' -ForegroundColor Cyan",
        "Write-Host ''",
        "function Find-Winget {",
        "    $cmd = Get-Command winget -ErrorAction SilentlyContinue",
        "    if ($cmd) { return $cmd.Source }",
        "    $wa = Join-Path $env:LOCALAPPDATA 'Microsoft\\WindowsApps\\winget.exe'",
        "    if (Test-Path $wa) { return $wa }",
        "    return $null",
        "}",
        "function Find-CodeCli {",
        "    foreach ($cand in @(",
        f"        {_ps_quote(code_cli)},",
        "        \"$env:LOCALAPPDATA\\Programs\\Microsoft VS Code\\bin\\code.cmd\",",
        "        \"$env:ProgramFiles\\Microsoft VS Code\\bin\\code.cmd\",",
        "        \"${env:ProgramFiles(x86)}\\Microsoft VS Code\\bin\\code.cmd\"",
        "    )) {",
        "        if ($cand -and (Test-Path $cand)) { return $cand }",
        "    }",
        "    $c = Get-Command code.cmd -ErrorAction SilentlyContinue",
        "    if ($c) { return $c.Source }",
        "    $c2 = Get-Command code -ErrorAction SilentlyContinue",
        "    if ($c2 -and $c2.Source -like '*.cmd') { return $c2.Source }",
        "    return $null",
        "}",
        "$allOk = $true",
    ]
    for idx, step in enumerate(steps, start=1):
        label_s = _ps_quote(f"[{idx}/{len(steps)}] {step.get('label', '프로그램 설치')}")
        cmd_preview = _ps_quote("실행 명령: " + step.get("displayCmd", ""))
        lines.extend([
            "Write-Host ''",
            f"Write-Host {label_s} -ForegroundColor Yellow",
            f"Write-Host {cmd_preview} -ForegroundColor DarkGray",
        ])
        if step.get("kind") == "vscode-ext":
            ext_id = _ps_quote(step["extId"])
            lines.extend([
                "$codeBin = Find-CodeCli",
                "if (-not $codeBin) {",
                "    Write-Host 'VS Code(code.cmd)를 찾지 못했어요. 먼저 Visual Studio Code를 설치한 뒤 다시 실행해 주세요.' -ForegroundColor Red",
                "    $allOk = $false",
                "} else {",
                f"    & $codeBin --install-extension {ext_id}",
                "    if ($LASTEXITCODE -ne 0) {",
                "        Write-Host \"확장 설치가 실패하거나 취소되었습니다 (종료 코드: $LASTEXITCODE)\" -ForegroundColor Red",
                "        $allOk = $false",
                "    }",
                "}",
            ])
        else:
            pkg_id = _ps_quote(step["packageId"])
            override_arg = step.get("override", "")
            lines.extend([
                "$wingetBin = Find-Winget",
                "if (-not $wingetBin) {",
                "    Write-Host 'winget(앱 설치 관리자)을 찾지 못했어요. Microsoft Store에서 [앱 설치 관리자]를 업데이트하거나 공식 사이트에서 설치해 주세요.' -ForegroundColor Red",
                "    $allOk = $false",
                "} else {",
                f"    $wArgs = @('install', '-e', '--id', {pkg_id}, '--accept-source-agreements', '--accept-package-agreements')",
            ])
            if override_arg:
                lines.append(f"    $wArgs += @('--override', {_ps_quote(override_arg)})")
            lines.extend([
                "    & $wingetBin @wArgs",
                "    if ($LASTEXITCODE -eq -1978335189) {",
                "        Write-Host '이미 최신 버전이 설치되어 있어요.' -ForegroundColor Green",
                "    } elseif ($LASTEXITCODE -ne 0) {",
                "        Write-Host \"설치가 완료되지 않았습니다 (종료 코드: $LASTEXITCODE)\" -ForegroundColor Red",
                "        $allOk = $false",
                "    }",
                "}",
            ])
    lines.extend([
        "Write-Host ''",
        "try {",
        "    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')",
        "    $machPath = [Environment]::GetEnvironmentVariable('Path', 'Machine')",
        "    $env:Path = \"$userPath;$machPath;$env:USERPROFILE\\.cargo\\bin\"",
        "} catch {}",
        "if ($allOk) {",
        "    Write-Host '설치 작업이 완료되었어요! 코드스텝 [준비] 탭에서 [설치 상태 다시 확인] 버튼을 눌러 주세요.' -ForegroundColor Green",
        "} else {",
        "    Write-Host '일부 항목을 완료하지 못했어요. 위 메시지를 확인한 뒤 다시 시도해 주세요.' -ForegroundColor Yellow",
        "}",
        "Write-Host ''",
        "Read-Host '창을 닫으려면 Enter 키를 누르세요'",
    ])
    return "\n".join(lines) + "\n"


def launch_installer_terminal(steps: list, title: str = "코드스텝 개발 환경 설치", code_cli: str = "", popen=None):
    """Open an interactive Windows PowerShell terminal window to install selected tools."""
    if not steps:
        return False, "설치할 항목이 없어요."
    if sys.platform != "win32":
        return False, "터미널 자동 설치 실행은 Windows에서만 지원해요."
    try:
        setup_dir = Path(tempfile.gettempdir()) / "codestep-setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        script_path = setup_dir / f"install_{int(time.time() * 1000)}_{os.getpid()}.ps1"
        script_path.write_bytes(build_installer_ps1(steps, title=title, code_cli=code_cli).encode("utf-8-sig"))
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "PYINSTALLER_RESET_ENVIRONMENT"):
            env.pop(key, None)
        runner = popen or subprocess.Popen
        runner(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return True, "설치 터미널 창을 열었어요. 설치 완료 후 [설치 상태 다시 확인]을 눌러 주세요."
    except OSError as error:
        return False, f"설치 터미널을 열지 못했어요: {error}"
