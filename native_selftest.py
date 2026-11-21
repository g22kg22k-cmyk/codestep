"""Local functional checks used to validate the source app and the frozen EXE."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import traceback


def run_checks(report_path, data_dir=None):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "python": sys.version.split()[0], "ui": "native Tk", "checks": []}
    app = None
    try:
        from native_app import CodeStepApp, ROUTES, _clean_prose_text
        from learning import LESSONS, SAMPLES, ProgressStore, is_unlocked
        from code_executor import run_code, run_workspace_script
        from python_bridge import scan_deliverables, write_text_safe
        with tempfile.TemporaryDirectory(prefix="native-check-", dir=data_dir or report_path.parent) as folder:
            app = CodeStepApp(data_dir=folder, hidden=True)
            report["pythonRuntime"] = app.runtime.get("label", "")
            app.progress["settings"]["sound"] = False
            callback_errors = []
            app.report_callback_exception = lambda *error: callback_errors.append("".join(traceback.format_exception(*error)))

            def pump(until=lambda: True, limit=9):
                deadline = time.monotonic() + limit
                while True:
                    app.update()
                    assert not callback_errors, callback_errors
                    if until():
                        break
                    assert time.monotonic() < deadline, "Native UI operation timed out"
                    time.sleep(0.02)

            for route, _, _ in ROUTES:
                app.nav_buttons[route].invoke()
                pump()
                assert app.route == route and app.content.winfo_children()
            assert app.winfo_class() == "Tk"
            assert len(app._icon_photos) == 4
            if sys.platform == "win32":
                import ctypes
                import ctypes.wintypes as wintypes

                user32 = ctypes.windll.user32
                user32.SendMessageW.restype = ctypes.c_void_p
                user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
                hwnd = int(app.wm_frame(), 16)
                assert len(app._win_hicons) == 2
                assert user32.SendMessageW(hwnd, 0x007F, 0, 0) == app._win_hicons[0]
                assert user32.SendMessageW(hwnd, 0x007F, 1, 0) == app._win_hicons[1]
            assert not any(name in sys.modules for name in ("webbrowser", "http.server", "server"))
            report["checks"].append("All seven native Tk tabs render (Setup, Python, Rust & tools); no browser or HTTP server imported")
            app.nav_buttons["setup"].invoke()
            pump()
            assert app.route == "setup"
            app.controls["setupLang"]["rust"].invoke()
            pump()
            assert app.setup_lang == "rust" and {"rustup", "msvc-buildtools", "vscode", "vscode-rust-analyzer"}.issubset(app.controls["setupInstall"])
            app.controls["setupLang"]["python"].invoke()
            pump()
            assert app.setup_lang == "python" and {"python3", "vscode", "vscode-python"}.issubset(app.controls["setupInstall"])
            app.nav_buttons["rust"].invoke()
            pump()
            assert app.route == "rust" and app.lang_filter == "rust" and "rust-basics" in app.expanded
            app.nav_buttons["python"].invoke()
            pump()
            assert app.route == "python" and app.lang_filter == "python" and "start" in app.expanded
            app.navigate("learn")
            pump()
            assert app.route == "python"
            app.navigate("review")
            app._set_review_lang_filter("rust")
            pump()
            assert app.review_lang_filter == "rust"
            app._set_review_lang_filter("all")
            pump()
            app.navigate("python")
            pump()
            app._set_level_filter("exam")
            assert app.level_filter == "exam" and "exam-eip" in app.expanded
            app._set_level_filter("all")
            # Verify quick-unlock toggle button renders cleanly in both states ("secondary" button kind)
            assert _clean_prose_text("**강조** `코드` $O(N)$") == "강조 코드 O(N)"
            app._toggle_quick_unlock()
            pump()
            assert app.progress["settings"]["unlockAll"] is True
            app._toggle_quick_unlock()
            pump()
            assert app.progress["settings"]["unlockAll"] is False
            app.start_lesson("numbers")
            assert app.session is None, "Locked lessons must stay locked"

            def answer_current(via_external_file=False):
                question = app.current_question()
                if question["type"] in ("choice", "fill"):
                    app.controls["choices"][question["answer"]].invoke()
                elif question["type"] == "order":
                    used = set()
                    for token in question["answer"]:
                        index = next(i for i, value in enumerate(question["tokens"]) if value == token and i not in used)
                        used.add(index)
                        app.controls["tokens"][index].invoke()
                elif question["type"] == "output":
                    app.controls["output_box"].insert("1.0", question["answer"])
                    app._sync_output_answer()
                elif via_external_file:
                    # Simulate external Python editor (IDLE/VS Code) modifying main.py on disk
                    write_text_safe(app.session["scriptPath"], question["solution"])
                    pump(lambda: app.session["feedback"].get("correct") and not app.session["running"], limit=10)
                    assert app.lesson_editor.get().strip() == question["solution"].strip()
                    prev_index = app.session["index"]
                    # Verify Ctrl+Enter advances to next step when answer is correct
                    app.lesson_editor.text.event_generate("<Control-Return>")
                    pump()
                    if app.session["index"] == prev_index:
                        assert app._handle_ctrl_enter() == "break"
                        pump()
                    assert app.session["index"] == prev_index + 1 or app.session["done"]
                    return
                else:
                    app.lesson_editor.set(question["solution"])
                app.controls["check"].invoke()
                pump(lambda: not app.session["running"])
                assert app.session["feedback"].get("correct"), (question["id"], app.session["feedback"])
                if question["type"] == "code":
                    prev_index = app.session["index"]
                    assert app._handle_ctrl_enter() == "break"
                    pump()
                    assert app.session["index"] == prev_index + 1 or app.session["done"]
                else:
                    app.controls["check"].invoke()
                    pump()

            python_lessons = [l for l in LESSONS if l.get("lang", "python") == "python"]
            rust_lessons = [l for l in LESSONS if l.get("lang") == "rust"]
            for index, lesson in enumerate(python_lessons):
                assert is_unlocked(app.progress, lesson["id"])
                app.start_lesson(lesson["id"])
                pump()
                assert app.session["index"] == -1
                app.controls["check"].invoke()
                if index == 0:
                    question = app.current_question()
                    wrong = next(value for value in question["options"] if value != question["answer"])
                    app.controls["choices"][wrong].invoke()
                    app.controls["check"].invoke()
                    assert app.session["hearts"] == 4 and question["id"] in app.progress["mistakes"]
                for q_pos, q in enumerate(lesson["questions"]):
                    # Verify step examples switching & inline concept drawer on practical lessons
                    if lesson["id"] == "files-io" and q_pos == 0:
                        app._select_lesson_example(1, "ref")
                        pump()
                    if lesson["id"] == "files-io" and q["type"] == "code":
                        app.toggle_concept()
                        app._select_lesson_example(2, "code")
                        pump()
                        assert app.session.get("conceptOpen") is True
                    # Verify external file watcher + auto-grading on practical file-IO lesson
                    use_external = lesson["id"] == "files-io" and q["type"] == "code"
                    answer_current(via_external_file=use_external)
                assert app.session["done"] and lesson["id"] in app.progress["completed"]
                assert app.session["accuracy"] == (75 if index == 0 else 100)
                app.controls["check"].invoke()
                pump()

            expected_completed = len(python_lessons)
            expected_xp = 20 + sum(50 if l.get("kind") == "midterm" else 25 for l in python_lessons[1:])

            # Exercise Rust track UI, .rs workspace preparation, and Q1-Q4 flow
            assert rust_lessons and is_unlocked(app.progress, rust_lessons[0]["id"])
            if app.rust_runtime["available"]:
                for lesson in rust_lessons:
                    app.start_lesson(lesson["id"])
                    pump()
                    app.controls["check"].invoke()
                    for q in lesson["questions"]:
                        answer_current()
                    assert app.session["done"] and lesson["id"] in app.progress["completed"]
                    app.controls["check"].invoke()
                    pump()
                expected_completed += len(rust_lessons)
                expected_xp += sum(50 if l.get("kind") == "midterm" else 25 for l in rust_lessons)
            else:
                app.start_lesson(rust_lessons[0]["id"])
                pump()
                app.controls["check"].invoke()
                for q in rust_lessons[0]["questions"][:-1]:
                    answer_current()
                assert app.current_question()["type"] == "code"
                assert app.session["scriptPath"].name == "main.rs"
                assert app.session["scriptPath"].is_file()
                app.lesson_editor.set(app.current_question()["solution"])
                app.controls["check"].invoke()
                pump(lambda: not app.session["running"])
                assert app.session["result"].get("missingCompiler") is True
                app.toggle_hint()
                app.reveal_solution()
                pump()
                app.close_lesson()
                pump()

            assert app.progress["xp"] == expected_xp and len(app.progress["completed"]) == expected_completed
            report["checks"].append(f"{expected_completed} complete lesson flows (incl. Rust track & .rs sync), external .py sync & deliverable recognition")
            app.navigate("review")
            app.start_review()
            while app.session and not app.session["done"]:
                if app.current_question().get("lang") == "rust" and not app.rust_runtime["available"]:
                    app.close_lesson()
                    pump()
                    break
                answer_current()
            if app.session and app.session.get("done"):
                app.close_lesson()
            elif app.session:
                app.close_lesson()
            if not app.rust_runtime["available"] and rust_lessons[0]["questions"][-1]["id"] in app.progress["mistakes"]:
                expected_xp += 3
                assert app.progress["xp"] == expected_xp and app.progress["reviewCount"] == 1
            else:
                assert app.progress["xp"] == expected_xp + 3 and not app.progress["mistakes"] and app.progress["reviewCount"] == 1
                expected_xp += 3
            report["checks"].append("Wrong answers persist; review removes the resolved Python mistake and awards 3 XP once")

            python_path = app.runtime.get("path") if app.runtime.get("available") else None
            python_samples = [s for s in SAMPLES if s.get("lang", "python") == "python"]
            with tempfile.TemporaryDirectory(prefix="curr-run-", dir=folder) as run_root:
                for lesson in python_lessons:
                    ex_dir = Path(run_root) / f"ex_{lesson['id']}"
                    ex_dir.mkdir(parents=True, exist_ok=True)
                    ex_script = ex_dir / "example.py"
                    write_text_safe(ex_script, lesson["example"])
                    result = run_workspace_script(ex_script, ex_dir, python_path=python_path)
                    assert result["ok"], (lesson["id"], result)
                for sample in python_samples:
                    s_dir = Path(run_root) / f"sample_{sample['id']}"
                    s_dir.mkdir(parents=True, exist_ok=True)
                    s_script = s_dir / "sample.py"
                    write_text_safe(s_script, sample["code"])
                    result = run_workspace_script(s_script, s_dir, stdin=sample.get("stdin", ""), python_path=python_path)
                    assert result["ok"], (sample["id"], result)
            report["checks"].append(f"All {len(python_lessons) + len(python_samples)} Python curriculum & sample programs execute cleanly")

            app.navigate("playground")
            app._switch_playground_lang("rust")
            pump()
            assert app.play_script_path.name == "practice.rs" and app.play_script_path.is_file()
            assert app.repl_entry is None
            app._switch_playground_lang("python")
            pump()
            assert app.play_script_path.name == "practice.py" and app.repl_entry is not None
            # Test practical deliverable generation (memo.txt) in Playground
            app.editor.set('with open("memo.txt", "w", encoding="utf-8") as f:\n    f.write("실기 파일 결과물\\n")\nprint("네이티브 실행")')
            app.controls["run"].invoke()
            pump(lambda: not app.play_running)
            assert app.play_result["ok"] and app.play_result["output"] == "네이티브 실행\n"
            deliv = scan_deliverables(app.play_task_dir, script_name="practice.py")
            assert any(d["name"] == "memo.txt" and d["isOutput"] for d in deliv), deliv

            app.editor.set("while True:\n    pass")
            app.controls["run"].invoke()
            ticks = []
            app.after(100, lambda: ticks.append(True))
            pump(lambda: not app.play_running)
            assert ticks and not app.play_result["ok"] and "5초" in app.play_result["error"]
            app.editor.set('print("복구 완료")')
            app.controls["run"].invoke()
            pump(lambda: not app.play_running)
            assert app.play_result["ok"] and app.play_result["output"] == "복구 완료\n"
            assert app.repl_entry is not None
            app.repl_entry.insert(0, "val = 6 * 7")
            app._submit_repl()
            pump(lambda: not app.repl_running)
            app.repl_entry.insert(0, "val + 8")
            app._submit_repl()
            pump(lambda: not app.repl_running)
            assert "50\n" in app.console.get("1.0", "end")
            report["checks"].append("Native playground syncs practice.py, runs interactive >>> REPL, detects deliverables, and recovers from infinite loop")

            for code in ("import os", 'open("sample.txt", "w")', "print((1).__class__)", 'x = "a" * 1000000000'):
                result = run_code(code)
                assert not result["ok"], code
            long_korean = "가" * 4500
            assert run_code(f'print("{long_korean}")')["output"] == long_korean + "\n"
            result = run_code('print(input())', "한글 입력\n")
            assert result["ok"] and result["output"] == "한글 입력\n"
            report["checks"].append("Restricted sandbox checks, memory limit, Korean code and stdin remain intact")

            app.navigate("settings")
            app.set_goal(40)
            app.store.export(Path(folder) / "export.json")
            exported = app.store.read_import(Path(folder) / "export.json")
            assert exported == app.progress
            expected_progress = app.progress.copy()
            app.close()
            app = None
            restored = ProgressStore(folder)
            assert restored.progress == expected_progress
            assert restored.draft["code"] == 'print("복구 완료")'
            report["checks"].append("Progress, goal, code draft and export/import survive application shutdown")
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app:
            try:
                app.destroy()
            except Exception:
                pass
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
