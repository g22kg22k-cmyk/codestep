import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from code_executor import run_repl_command, run_workspace_script
from learning import LESSON_BY_ID, QUESTION_BY_ID, fresh_progress, is_unlocked, normalize_progress
from native_app import _get_chime_bytes
from python_bridge import (
    WorkspaceManager,
    build_installer_ps1,
    discover_python_runtime,
    discover_setup_status,
    discover_vscode_cli_and_extensions,
    get_setup_catalog,
    launch_installer_terminal,
    scan_deliverables,
    verify_workspace_question,
    write_text_safe,
)


class PythonBridgeTests(unittest.TestCase):
    def test_workspace_preserves_external_edits_and_restores_on_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            ws = WorkspaceManager(Path(folder), isolated=True)
            task_dir, script_path, text = ws.prepare_workspace(
                ws.task_dir("files-io-4"),
                "main.py",
                "# starter\n",
                fixtures={"scores.txt": "민수,80\n"},
            )
            self.assertEqual(text, "# starter\n")
            self.assertTrue((task_dir / "scores.txt").is_file())

            # Simulate user editing main.py externally in IDLE / VS Code
            write_text_safe(script_path, 'print("외부 수정")\n')
            _, _, reloaded = ws.prepare_workspace(
                task_dir, "main.py", "# starter\n", fixtures={"scores.txt": "민수,80\n"}
            )
            self.assertEqual(reloaded, 'print("외부 수정")\n')

            _, _, reset_text = ws.prepare_workspace(
                task_dir, "main.py", "# starter\n", fixtures={"scores.txt": "민수,80\n"}, reset_code=True
            )
            self.assertEqual(reset_text, "# starter\n")

    def test_real_execution_supports_modules_and_files_in_both_modes(self):
        runtime = discover_python_runtime()
        python_candidates = [runtime["path"]] if runtime["available"] else []
        python_candidates.append(None)  # Always verify embedded fallback too

        for py_path in python_candidates:
            with self.subTest(python_path=py_path), tempfile.TemporaryDirectory() as folder:
                work_dir = Path(folder)
                script = work_dir / "main.py"
                write_text_safe(
                    script,
                    'import math\n'
                    'with open("out.txt", "w", encoding="utf-8") as f:\n'
                    '    f.write(f"{round(math.pi, 2)}\\n")\n'
                    'print("안녕", input())\n',
                )
                result = run_workspace_script(script, work_dir, stdin="파이썬\n", python_path=py_path)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["output"], "안녕 파이썬\n")
                self.assertEqual((work_dir / "out.txt").read_text(encoding="utf-8"), "3.14\n")

    def test_function_checks_prevent_hardcoded_stdout_fakes(self):
        question = QUESTION_BY_ID["project-4"]
        runtime = discover_python_runtime()
        with tempfile.TemporaryDirectory() as folder:
            ws = WorkspaceManager(Path(folder), isolated=True)
            task_dir, script_path, _ = ws.prepare_workspace(ws.task_dir("project-4"), "main.py", "")
            # Hardcoded print(12) without implementing sum_even must fail functionChecks
            write_text_safe(script_path, "def sum_even(numbers):\n    return 12\nprint(sum_even([1,2,3,4,5,6]))\n")
            fake_res = verify_workspace_question(task_dir, script_path, question, runtime, isolated=False)
            self.assertFalse(fake_res["passed"])

            # Real implementation passes all functionChecks
            write_text_safe(script_path, question["solution"])
            real_res = verify_workspace_question(task_dir, script_path, question, runtime, isolated=False)
            self.assertTrue(real_res["passed"], real_res)

    def test_file_deliverables_verification_and_isolated_auto_verify(self):
        runtime = discover_python_runtime()
        for qid, expected_file in (("files-io-4", "report.txt"), ("json-project-4", "summary.json")):
            question = QUESTION_BY_ID[qid]
            with self.subTest(qid=qid), tempfile.TemporaryDirectory() as folder:
                ws = WorkspaceManager(Path(folder), isolated=True)
                task_dir, script_path, _ = ws.prepare_workspace(
                    ws.task_dir(qid), "main.py", question["starter"], fixtures=question["fixtures"]
                )
                write_text_safe(script_path, question["solution"])

                # Isolated auto-verify validates deliverable without writing output into live task_dir
                iso_res = verify_workspace_question(task_dir, script_path, question, runtime, isolated=True)
                self.assertTrue(iso_res["passed"], iso_res)
                self.assertTrue(any(d["name"] == expected_file and d["isOutput"] for d in iso_res["deliverables"]))
                self.assertFalse((task_dir / expected_file).exists())

                # Explicit check writes real deliverable file into live task_dir
                live_res = verify_workspace_question(task_dir, script_path, question, runtime, isolated=False)
                self.assertTrue(live_res["passed"], live_res)
                self.assertTrue((task_dir / expected_file).is_file())
                scanned = scan_deliverables(task_dir, "main.py", question["fixtures"])
                self.assertTrue(any(d["name"] == expected_file and d["isOutput"] for d in scanned))

    def test_settings_normalization_and_unlock_all(self):
        p = fresh_progress()
        self.assertFalse(is_unlocked(p, "files-io"))
        p["settings"].update(pythonPath="C:/Python312/python.exe", workspaceDir="D:/Work", autoVerify=False, unlockAll=True)
        clean = normalize_progress(p)
        self.assertEqual(clean["settings"]["pythonPath"], "C:/Python312/python.exe")
        self.assertEqual(clean["settings"]["workspaceDir"], "D:/Work")
        self.assertFalse(clean["settings"]["autoVerify"])
        self.assertTrue(clean["settings"]["unlockAll"])
        self.assertIn("files-io", LESSON_BY_ID)
        self.assertTrue(is_unlocked(clean, "files-io"))

    def test_repl_execution_and_chime_audio(self):
        runtime = discover_python_runtime()
        python_candidates = [runtime["path"]] if runtime["available"] else []
        python_candidates.append(None)

        for py_path in python_candidates:
            with self.subTest(python_path=py_path), tempfile.TemporaryDirectory() as folder:
                work_dir = Path(folder)
                res1 = run_repl_command("1 + 2", work_dir, python_path=py_path)
                self.assertTrue(res1["ok"] and res1["committed"], res1)
                self.assertEqual(res1["output"], "3\n")

                history = ["x = 10"]
                res2 = run_repl_command("x * 4", work_dir, history=history, python_path=py_path)
                self.assertTrue(res2["ok"] and res2["committed"], res2)
                self.assertEqual(res2["output"], "40\n")

                err_res = run_repl_command("unknown_name + 1", work_dir, history=history, python_path=py_path)
                self.assertFalse(err_res["ok"] or err_res["committed"])
                self.assertIn("NameError", err_res["error"])

        ok_wav = _get_chime_bytes(True)
        err_wav = _get_chime_bytes(False)
        self.assertTrue(ok_wav.startswith(b"RIFF") and err_wav.startswith(b"RIFF"))
        self.assertGreater(len(ok_wav), 1000)
        self.assertGreater(len(err_wav), 1000)

    def test_taskbar_icon_assets_and_frames(self):
        assets = Path(__file__).resolve().parents[1] / "assets"
        ico = assets / "codestep.ico"
        self.assertTrue(ico.is_file())
        raw = ico.read_bytes()
        reserved, icon_type, count = struct.unpack_from("<HHH", raw, 0)
        self.assertEqual((reserved, icon_type), (0, 1))
        self.assertGreaterEqual(count, 8)
        sizes = []
        for idx in range(count):
            w, h, _, _, _, bpp, size, offset = struct.unpack_from("<BBBBHHII", raw, 6 + idx * 16)
            dim = 256 if w == 0 else w
            sizes.append(dim)
            self.assertEqual(bpp, 32)
            payload = raw[offset:offset + size]
            if dim <= 48:
                self.assertEqual(struct.unpack_from("<I", payload, 0)[0], 40)
            else:
                self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
        for expected_dim in (16, 24, 32, 40, 48, 64, 128, 256):
            self.assertIn(expected_dim, sizes)
        for png_dim in (32, 48, 64, 256):
            png = assets / f"codestep_{png_dim}.png"
            self.assertTrue(png.is_file() and png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_advanced_function_checks_and_friendly_stdout_diff(self):
        runtime = discover_python_runtime()
        with tempfile.TemporaryDirectory() as folder:
            ws = WorkspaceManager(Path(folder), isolated=True)

            # 1) kwargs verification rejects hardcoded "-" separator
            q_kw = QUESTION_BY_ID["scope-closure-args-4"]
            t_dir, s_path, _ = ws.prepare_workspace(ws.task_dir("scope-closure-args-4"), "main.py", "")
            write_text_safe(
                s_path,
                'def join_tags(prefix, *tags, sep="-"):\n'
                '    return "-".join(prefix + t for t in tags)\n',
            )
            bad_kw = verify_workspace_question(t_dir, s_path, q_kw, runtime, isolated=True)
            self.assertFalse(bad_kw["passed"])
            write_text_safe(s_path, q_kw["solution"])
            good_kw = verify_workspace_question(t_dir, s_path, q_kw, runtime, isolated=True)
            self.assertTrue(good_kw["passed"], good_kw)

            # 2) isGenerator check rejects plain list return and accepts yield generator
            q_gen = QUESTION_BY_ID["gen-decorator-4"]
            t_dir, s_path, _ = ws.prepare_workspace(ws.task_dir("gen-decorator-4"), "main.py", "")
            write_text_safe(
                s_path,
                "def even_gen(limit):\n    return list(range(0, limit + 1, 2))\n"
                "def sum_evens_up_to(limit):\n    return sum(even_gen(limit))\n",
            )
            bad_gen = verify_workspace_question(t_dir, s_path, q_gen, runtime, isolated=True)
            self.assertFalse(bad_gen["passed"])
            write_text_safe(s_path, q_gen["solution"])
            good_gen = verify_workspace_question(t_dir, s_path, q_gen, runtime, isolated=True)
            self.assertTrue(good_gen["passed"], good_gen)

            # 3) className/baseClassName inheritance check rejects standalone calc_discounted
            q_oop = QUESTION_BY_ID["eip-oop-trace-4"]
            t_dir, s_path, _ = ws.prepare_workspace(ws.task_dir("eip-oop-trace-4"), "main.py", "")
            write_text_safe(
                s_path,
                "class DiscountItem:\n    def __init__(self, n, p, r): pass\n    def final_price(self): return 8000\n"
                "def calc_discounted(price, rate): return (price * (100 - rate)) // 100\n",
            )
            bad_oop = verify_workspace_question(t_dir, s_path, q_oop, runtime, isolated=True)
            self.assertFalse(bad_oop["passed"])
            write_text_safe(s_path, q_oop["solution"])
            good_oop = verify_workspace_question(t_dir, s_path, q_oop, runtime, isolated=True)
            self.assertTrue(good_oop["passed"], good_oop)

            # 4) Stdout mismatch uses beginner-friendly label and shows actual vs expected
            q_hello = QUESTION_BY_ID["hello-4"]
            t_dir, s_path, _ = ws.prepare_workspace(ws.task_dir("hello-4"), "main.py", "")
            write_text_safe(s_path, 'print("Hi Python")\n')
            diff_res = verify_workspace_question(t_dir, s_path, q_hello, runtime, isolated=True)
            self.assertFalse(diff_res["passed"])
            stdout_chk = next(c for c in diff_res["checks"] if "stdout" in c["label"])
            self.assertEqual(stdout_chk["label"], "화면 출력 결과(stdout)")
            self.assertIn("내 출력:", stdout_chk["detail"])
            self.assertIn("목표:", stdout_chk["detail"])

    def test_registered_pythons_are_ordered_newest_first(self):
        from python_bridge import order_registered_pythons
        entries = [
            ("PythonCore", "3.9", r"C:\py39\python.exe"),
            ("PyLauncher", "", r"C:\launcher\py.exe"),
            ("PythonCore", "3.15", r"C:\py315\python.exe"),
            ("PythonCore", "3.14", ""),
            ("PythonCore", "3.12", r"C:\py312\python.exe"),
        ]
        self.assertEqual(order_registered_pythons(entries),
                         [r"C:\py315\python.exe", r"C:\py312\python.exe", r"C:\py39\python.exe"])

    @unittest.skipUnless(sys.platform == "win32", "PEP 514 registry is Windows only")
    def test_install_manager_pythons_are_discovered(self):
        # Python installed with the python.org install manager lives in %LOCALAPPDATA%\Python\pythoncore-*.
        # The app used to miss it entirely and fell back to the built-in runner without IDLE.
        from python_bridge import _candidate_pythons, _read_pep514_registry
        registered = [exe for _, _, exe in _read_pep514_registry() if exe and Path(exe).is_file()]
        if not registered:
            self.skipTest("no Python registered on this PC")
        with patch.object(sys, "frozen", True, create=True):
            paths = [str(path).lower() for path, _ in _candidate_pythons()]
        for exe in registered:
            self.assertIn(exe.lower(), paths)

    def test_output_difference_points_at_the_first_wrong_character(self):
        from python_bridge import describe_output_difference as diff
        target = "Hello, Python!"
        cases = [
            ("hello, Python!", ["1번째 줄 1번째 글자", "'h'", "'H'", "대문자와 소문자"]),
            ("Hello Python!", ["6번째 글자", "빈칸", "','"]),
            ("Hello， Python!", ["6번째 글자", "전각 기호"]),
            ("Hello, Python! ", ["필요 없는 빈칸"]),
            ("Hello, Python", ["'!' 부분이 빠졌어요"]),
        ]
        for actual, expected_parts in cases:
            with self.subTest(actual=actual):
                message = diff(actual, target)
                for part in expected_parts:
                    self.assertIn(part, message)
                self.assertIn("내 출력:", message)
                self.assertIn("목표:", message)
        self.assertIn("2번째 줄", diff("1", "1\n2"))
        self.assertIn("목표에 없는 출력", diff("1\n2\n3", "1\n2"))

    def test_setup_catalog_detection_and_installer_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            fake_home = Path(folder)
            ext_root = fake_home / ".vscode" / "extensions"
            (ext_root / "ms-python.python-2026.0.0").mkdir(parents=True)
            (ext_root / "rust-lang.rust-analyzer-0.4.0").mkdir(parents=True)

            vsc_dir = Path(folder) / "VSCode"
            (vsc_dir / "bin").mkdir(parents=True)
            fake_code_exe = vsc_dir / "Code.exe"
            fake_code_cmd = vsc_dir / "bin" / "code.cmd"
            fake_code_exe.write_text("", encoding="utf-8")
            fake_code_cmd.write_text("", encoding="utf-8")

            ext_info = discover_vscode_cli_and_extensions(str(fake_code_exe), home_dir=fake_home)
            self.assertEqual(ext_info["codeCli"], str(fake_code_cmd))
            self.assertTrue(ext_info["pyExt"])
            self.assertTrue(ext_info["rustExt"])

            with patch.object(Path, "is_dir", side_effect=PermissionError("denied")):
                denied = discover_vscode_cli_and_extensions("", home_dir=fake_home)
            self.assertIsNone(denied["pyExt"])
            self.assertIsNone(denied["rustExt"])

            status = discover_setup_status(
                python_runtime={"available": False, "version": "3.12.14", "hasIdle": False},
                rust_runtime={"available": False, "version": "", "cargo": ""},
                editors={"vscode": str(fake_code_exe)},
                home_dir=fake_home,
            )
            catalog = get_setup_catalog(status)
            self.assertEqual([item["id"] for item in catalog["python"]], ["python3", "vscode", "vscode-python"])
            self.assertEqual([item["id"] for item in catalog["rust"]], ["msvc-buildtools", "rustup", "vscode", "vscode-rust-analyzer"])
            self.assertTrue(catalog["python"][2]["installed"])
            self.assertTrue(catalog["rust"][3]["installed"])

            ps1 = build_installer_ps1(
                [catalog["rust"][0]["step"], catalog["rust"][1]["step"], catalog["rust"][3]["step"]],
                title="Rust 환경 일괄 설치",
                code_cli=str(fake_code_cmd),
            )
            self.assertIn("Rustlang.Rustup", ps1)
            self.assertIn("Microsoft.VisualStudio.2022.BuildTools", ps1)
            self.assertIn("Microsoft.VisualStudio.Workload.VCTools", ps1)
            self.assertIn("--install-extension 'rust-lang.rust-analyzer'", ps1)

            spawned = {}

            def fake_popen(cmd, env=None, creationflags=0):
                spawned["cmd"] = cmd
                spawned["env"] = env
                spawned["flags"] = creationflags

            with patch.dict(os.environ, {"PYTHONHOME": "C:\\bad", "TCL_LIBRARY": "C:\\bad", "TK_LIBRARY": "C:\\bad"}):
                ok, msg = launch_installer_terminal([catalog["python"][0]["step"]], title="Python 설치", popen=fake_popen)
            if sys.platform == "win32":
                self.assertTrue(ok, msg)
                self.assertEqual(spawned["cmd"][:5], ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
                ps1_path = Path(spawned["cmd"][5])
                self.assertTrue(ps1_path.is_file())
                self.assertNotIn("PYTHONHOME", spawned["env"])
                self.assertNotIn("TCL_LIBRARY", spawned["env"])
                self.assertEqual(spawned["flags"], getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                ps1_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
