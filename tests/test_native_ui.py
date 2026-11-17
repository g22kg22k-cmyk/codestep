import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import desktop

desktop.configure_tk()

import learning
import native_app


def _extract_code_text(code_shell):
    """Return text displayed inside a code_block widget wrapper."""
    for child in code_shell.winfo_children():
        if isinstance(child, tk.Text):
            return child.get("1.0", "end-1c")
    raise AssertionError("No tk.Text widget found inside code_block")


class NativeUiRegressionTests(unittest.TestCase):
    """Regression tests for in-place Tk updates, flicker avoidance, and Ctrl+Return handling."""

    def _make_app(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        try:
            app = native_app.CodeStepApp(data_dir=tmpdir.name, hidden=True)
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable in test environment: {exc}")
        self.addCleanup(self._destroy_app, app)
        return app

    @staticmethod
    def _destroy_app(app):
        try:
            if app.session:
                app.close_lesson()
        except Exception:
            pass
        try:
            for after_id in app.tk.call("after", "info"):
                try:
                    app.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            app.close()
        except Exception:
            pass

    def test_choice_and_hint_update_in_place_without_render_lesson(self):
        app = self._make_app()
        lesson_id = learning.UNITS[0]["lessons"][0]["id"]
        app.start_lesson(lesson_id)
        self.assertEqual(app.session["index"], -1)

        # Advance past concept page to Q1 (choice).
        app.next_question()
        q0 = app.current_question()
        self.assertEqual(q0["type"], "choice")

        scroll_id = id(app.lesson_scroll)
        choice_map = app.controls["choices"]
        choice_ids = {opt: id(btn) for opt, btn in choice_map.items()}
        hint_ui = app.controls["hint_ui"]
        hint_bar_id = id(hint_ui["bar"])
        check_btn = app.controls["check"]
        check_req_w = check_btn.winfo_reqwidth()

        wrong_opt = next(opt for opt in q0["options"] if opt != q0["answer"])
        right_opt = q0["answer"]

        delete_calls = []
        orig_canvas_delete = tk.Canvas.delete

        def spy_delete(widget, *args):
            if widget in choice_map.values() or widget is check_btn:
                delete_calls.append((widget, args))
            return orig_canvas_delete(widget, *args)

        app.update_idletasks()
        with (
            patch.object(app, "render_lesson", wraps=app.render_lesson) as spy_render,
            patch.object(tk.Canvas, "delete", spy_delete),
        ):
            app.choose(wrong_opt)
            self.assertEqual(delete_calls, [])

            app.toggle_hint()
            app.check_answer()
            app.update_idletasks()

            self.assertEqual(spy_render.call_count, 0)
            self.assertEqual(delete_calls, [])
            self.assertEqual(id(app.lesson_scroll), scroll_id)
            self.assertEqual({k: id(v) for k, v in app.controls["choices"].items()}, choice_ids)
            self.assertEqual(id(app.controls["hint_ui"]["bar"]), hint_bar_id)

            # Hint stays open and wrong check marks only the chosen option with coral border.
            self.assertTrue(app.session["hint"])
            self.assertGreater(len(hint_ui["hint_slot"].winfo_children()), 0)
            self.assertGreater(len(hint_ui["feedback_slot"].winfo_children()), 0)
            self.assertEqual(choice_map[wrong_opt]._border, "#b85c50")
            self.assertEqual(choice_map[wrong_opt]._kind, "ghost")
            self.assertEqual(check_btn.winfo_reqwidth(), check_req_w)

            # Choosing another option clears stale wrong feedback while keeping hint open.
            app.choose(right_opt)
            app.update_idletasks()

            self.assertEqual(spy_render.call_count, 0)
            self.assertEqual(delete_calls, [])
            self.assertEqual(app.session["feedback"], {})
            self.assertEqual(hint_ui["feedback_slot"].grid_info(), {})
            self.assertTrue(app.session["hint"])
            self.assertGreater(len(hint_ui["hint_slot"].winfo_children()), 0)
            self.assertEqual(choice_map[right_opt]._kind, "secondary")
            self.assertEqual(choice_map[wrong_opt]._kind, "ghost")

            # Correct check updates feedback and footer width stays steady.
            app.check_answer()
            app.update_idletasks()

            self.assertEqual(spy_render.call_count, 0)
            self.assertEqual(choice_map[right_opt]._kind, "secondary")
            # Changing check caption ("정답 확인" -> "다음으로...") updates only check_btn, never choices.
            self.assertTrue(all(w is check_btn for w, _ in delete_calls))
            self.assertTrue(app.session["feedback"].get("correct"))
            self.assertGreater(len(hint_ui["feedback_slot"].winfo_children()), 0)
            self.assertEqual(check_btn._min_width, 220)
            self.assertEqual(check_btn.winfo_reqwidth(), check_req_w)

    def test_fill_and_order_update_in_place_without_render_lesson(self):
        app = self._make_app()
        lesson_id = learning.UNITS[0]["lessons"][0]["id"]
        app.start_lesson(lesson_id)
        app.next_question()  # Q1 choice

        q0 = app.current_question()
        app.choose(q0["answer"])
        app.check_answer()
        app.next_question()  # Q2 fill

        q1 = app.current_question()
        self.assertEqual(q1["type"], "fill")
        fill_scroll_id = id(app.lesson_scroll)
        fill_box, template = app.controls["fill_code"]
        fill_box_id = id(fill_box)
        fill_choice_ids = {k: id(v) for k, v in app.controls["choices"].items()}
        self.assertIn("___", template)
        self.assertIn("___", _extract_code_text(fill_box))

        with patch.object(app, "render_lesson", wraps=app.render_lesson) as spy_render:
            app.choose(q1["answer"])
            app.update_idletasks()

            self.assertEqual(spy_render.call_count, 0)
            self.assertEqual(id(app.lesson_scroll), fill_scroll_id)
            self.assertEqual(id(app.controls["fill_code"][0]), fill_box_id)
            self.assertEqual({k: id(v) for k, v in app.controls["choices"].items()}, fill_choice_ids)
            updated_text = _extract_code_text(fill_box)
            self.assertNotIn("___", updated_text)
            self.assertIn(str(q1["answer"]), updated_text)

            app.check_answer()
            self.assertEqual(spy_render.call_count, 0)
            self.assertTrue(app.session["feedback"].get("correct"))

        app.next_question()  # Q3 order
        q2 = app.current_question()
        self.assertEqual(q2["type"], "order")
        order_scroll_id = id(app.lesson_scroll)
        token_ids = [id(btn) for btn in app.controls["tokens"]]
        sel_frame_id = id(app.controls["order_selection"])
        preview_id = id(app.controls["order_preview"])

        # Map each token in q2["answer"] to a distinct index in q2["tokens"].
        remaining = list(enumerate(q2["tokens"]))
        answer_indices = []
        for target in q2["answer"]:
            for pos, (tok_idx, tok_val) in enumerate(remaining):
                if tok_val == target:
                    answer_indices.append(tok_idx)
                    remaining.pop(pos)
                    break

        with patch.object(app, "render_lesson", wraps=app.render_lesson) as spy_render:
            first_idx = answer_indices[0]
            app.add_token(first_idx)
            self.assertEqual(app.controls["tokens"][first_idx]._state, "disabled")
            self.assertIn(q2["tokens"][first_idx], _extract_code_text(app.controls["order_preview"]))

            app.remove_token(0)
            self.assertEqual(app.controls["tokens"][first_idx]._state, "normal")

            for idx in answer_indices:
                app.add_token(idx)
            app.check_answer()
            app.update_idletasks()

            self.assertEqual(spy_render.call_count, 0)
            self.assertEqual(id(app.lesson_scroll), order_scroll_id)
            self.assertEqual([id(btn) for btn in app.controls["tokens"]], token_ids)
            self.assertEqual(id(app.controls["order_selection"]), sel_frame_id)
            self.assertEqual(id(app.controls["order_preview"]), preview_id)
            self.assertTrue(app.session["feedback"].get("correct"))

    def test_toggle_unit_updates_in_place_without_navigate(self):
        app = self._make_app()
        app.navigate("python")
        self.assertTrue(app.unit_rows)
        unit_id = next(iter(app.unit_rows))
        scroll_id = id(app.scroll)
        initial_expanded = unit_id in app.expanded
        path_wrap = app.unit_rows[unit_id][0]

        with patch.object(app, "navigate", wraps=app.navigate) as spy_nav:
            app.toggle_unit(unit_id)
            app.update_idletasks()
            self.assertEqual(spy_nav.call_count, 0)
            self.assertEqual(id(app.scroll), scroll_id)
            self.assertEqual(unit_id in app.expanded, not initial_expanded)
            if unit_id in app.expanded:
                self.assertGreater(len(path_wrap.winfo_children()), 0)
            else:
                self.assertEqual(len(path_wrap.winfo_children()), 0)

            app.toggle_unit(unit_id)
            app.update_idletasks()
            self.assertEqual(spy_nav.call_count, 0)
            self.assertEqual(id(app.scroll), scroll_id)
            self.assertEqual(unit_id in app.expanded, initial_expanded)

    def test_softbutton_configure_and_ctrl_return_guard(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable in test environment: {exc}")
        self.addCleanup(root.destroy)

        root.overrideredirect(True)
        root.geometry("260x200+10000+10000")

        hits = []
        root.bind("<Control-Return>", lambda e: hits.append("root-ctrl-enter"))

        btn = native_app.SoftButton(root, "Confirm", lambda: hits.append("btn"), kind="ghost")
        btn.pack()
        nav = native_app.NavPill(root, "home", "●", "Home", lambda: hits.append("nav"))
        nav.pack()
        node = native_app.LessonNode(root, "open", native_app.GREEN, lambda: hits.append("node"))
        node.pack()

        btn.configure(kind="secondary", disabledbackground="#eeeeee")
        self.assertEqual(btn._kind, "secondary")
        self.assertEqual(btn._dis_bg, "#eeeeee")
        root.update()

        for widget, expected_hit in ((btn, "btn"), (nav, "nav"), (node, "node")):
            hits.clear()
            widget.focus_force()
            root.update()
            # state=4 simulates Control+Return: focused widget must NOT fire its own command.
            widget.event_generate("<KeyPress-Return>", state=4)
            root.update()
            self.assertEqual(hits, ["root-ctrl-enter"], f"Control+Return leaked into {expected_hit}")

            hits.clear()
            widget.event_generate("<KeyPress-Return>", state=0)
            root.update()
            self.assertEqual(hits, [expected_hit], f"Plain Return failed on {expected_hit}")


class NativeUiFixTests(NativeUiRegressionTests):
    """Regression tests for bugs found in the full-program review."""

    # Run only the tests defined here, not the inherited ones a second time.
    test_choice_and_hint_update_in_place_without_render_lesson = None
    test_fill_and_order_update_in_place_without_render_lesson = None
    test_toggle_unit_updates_in_place_without_navigate = None
    test_softbutton_configure_and_ctrl_return_guard = None

    def test_clearing_results_keeps_the_other_languages_practice_file(self):
        app = self._make_app()
        app.navigate("playground")
        folder = Path(app.play_task_dir)
        (folder / "practice.rs").write_text('fn main() { println!("내 러스트 코드"); }\n', encoding="utf-8")
        (folder / "report.txt").write_text("결과", encoding="utf-8")
        app._clear_playground_deliverables()
        self.assertTrue((folder / "practice.py").is_file())
        self.assertTrue((folder / "practice.rs").is_file(), "Rust practice code must not be deleted from the Python tab")
        self.assertFalse((folder / "report.txt").exists())

    def test_repl_block_header_explains_instead_of_running(self):
        app = self._make_app()
        app.navigate("playground")
        app.repl_entry.insert(0, "for i in range(3):")
        with patch.object(app, "submit_task") as spy:
            app._submit_repl()
        spy.assert_not_called()
        self.assertFalse(app.repl_running)
        self.assertTrue(any("왼쪽 편집기" in text for _, text in app.repl_transcript))

    def test_code_typed_just_before_closing_a_lesson_is_saved(self):
        app = self._make_app()
        lesson = learning.UNITS[0]["lessons"][0]
        app.start_lesson(lesson["id"])
        app.next_question()
        while app.current_question()["type"] != "code":
            app.session["feedback"] = {"correct": True}
            app.next_question()
        script = Path(app.session["scriptPath"])
        app.lesson_editor.set('print("Hello, Python!")\n', notify=True)
        self.assertIsNotNone(app.sync_write_job, "the editor change should be waiting for a delayed save")
        app.close_lesson()
        self.assertEqual(script.read_text(encoding="utf-8"), 'print("Hello, Python!")\n')

    def test_sound_is_played_from_a_file(self):
        import winsound
        app = self._make_app()
        app.progress["settings"]["sound"] = True
        calls = []
        with patch.object(winsound, "PlaySound", side_effect=lambda sound, flags: calls.append((sound, flags))):
            app.play_sound(True)
            app.play_sound(False)
        self.assertEqual(len(calls), 2)
        for sound, flags in calls:
            # SND_MEMORY together with SND_ASYNC raises RuntimeError, so no chime was ever heard.
            self.assertFalse(flags & winsound.SND_MEMORY)
            self.assertTrue(flags & winsound.SND_FILENAME and flags & winsound.SND_ASYNC)
            self.assertTrue(Path(sound).read_bytes().startswith(b"RIFF"))


class TextPlacementAndContentUiTests(NativeUiRegressionTests):
    test_choice_and_hint_update_in_place_without_render_lesson = None
    test_fill_and_order_update_in_place_without_render_lesson = None
    test_toggle_unit_updates_in_place_without_navigate = None
    test_softbutton_configure_and_ctrl_return_guard = None

    def test_backslash_is_shown_as_a_backslash_in_the_korean_font(self):
        # The Korean UI font draws "\" as a won sign, so \d+ looked like ₩d+.
        self.assertEqual(native_app._clean_prose_text(r're.findall(r"\d+", s) · \n'), 're.findall(r"⧵d+", s) · ⧵n')

    @unittest.skipUnless(sys.platform == "win32", "glyph metrics come from Windows")
    def test_visible_letters_are_centered_not_the_line_box(self):
        app = self._make_app()
        # Korean letters sit high in Tk's line box: centering the box put them low, so they move up.
        dx, dy = native_app._text_ink_offset(app, (native_app.FONT, 10), "학습 시작")
        self.assertLess(dy, 0)
        self.assertLess(abs(dx), 2)
        # A leading emoji carries empty space on its left: the text moves left to look centered.
        dx, _ = native_app._text_ink_offset(app, (native_app.FONT, 9, "bold"), "⚡ 0 XP")
        self.assertLess(dx, 0)

    def test_concept_page_and_review_panel_show_common_mistakes(self):
        app = self._make_app()
        app.progress["settings"]["unlockAll"] = True
        app.start_lesson("error-reading")
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    texts.append(child.cget("text"))
                walk(child)

        walk(app.lesson_overlay)
        self.assertIn("자주 하는 실수", texts)
        self.assertTrue(any("NameError" in text for text in texts), "the real error message is shown")

    def test_failed_code_points_to_the_matching_mistake(self):
        lesson = learning.LESSON_BY_ID["error-reading"]
        match = native_app.CodeStepApp._matching_pitfall(
            lesson, "4번째 줄: NameError: name 'cont' is not defined (힌트)")
        self.assertIsNotNone(match)
        self.assertIn("철자", match["title"])
        syntax = native_app.CodeStepApp._matching_pitfall(
            learning.LESSON_BY_ID["conditions"], "3번째 줄: :(콜론)이 빠졌어요. if / elif / else / for / while / def / class 줄 끝에 ':'을 붙여 주세요. (expected ':')")
        self.assertIn("콜론", syntax["title"])
        rust = native_app.CodeStepApp._matching_pitfall(
            learning.LESSON_BY_ID["rust-variables"], "error[E0384]: cannot assign twice to immutable variable `x`")
        self.assertIn("let", rust["title"])
        self.assertIsNone(native_app.CodeStepApp._matching_pitfall(lesson, "1번째 줄: ZeroDivisionError: division by zero"))


class StartupErrorMessageTests(unittest.TestCase):
    def test_messages_name_the_cause_and_the_fix(self):
        denied = desktop.describe_startup_error(PermissionError(13, "Access is denied"), Path("C:/log.txt"))
        self.assertIn("PermissionError", denied)
        self.assertIn("랜섬웨어 방지", denied)
        self.assertIn("C:", denied)
        broken = desktop.describe_startup_error(KeyError("units"), None)
        self.assertIn("다시 복사", broken)
        self.assertNotIn("자세한 기록", broken)


if __name__ == "__main__":
    unittest.main()
