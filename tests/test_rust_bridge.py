"""Unit tests for rust_bridge discovery, diagnostics, harness generation, and mocked rustc execution."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import rust_bridge
from native_app import CodeStepApp
from python_bridge import verify_workspace_question


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@contextmanager
def _fake_toolchain(fake):
    """Send both the rustc call (subprocess.run) and the compiled program run (_run_exe) to one fake."""
    with mock.patch("rust_bridge.subprocess.run", side_effect=fake), \
            mock.patch("rust_bridge._run_exe", side_effect=lambda cmd, **kwargs: fake(cmd, **kwargs)):
        yield


class RustBridgeTests(unittest.TestCase):
    def test_error_translation_and_line_numbers(self):
        err = (
            "error[E0384]: cannot assign twice to immutable variable `x`\n"
            " --> main.rs:4:5\n"
            "  |\n"
            "4 |     x = 10;\n"
            "  |     ^^^^^^ cannot assign twice to immutable variable\n"
        )
        msg, line = rust_bridge.translate_rust_error(err)
        self.assertEqual(line, 4)
        self.assertIn("let mut", msg)

        err_move = "error[E0382]: borrow of moved value: `s`\n --> main.rs:7:20\n"
        msg2, line2 = rust_bridge.translate_rust_error(err_move)
        self.assertEqual(line2, 7)
        self.assertIn("소유권", msg2)

    def test_build_harness_rewrites_only_top_level_main_and_mut_args(self):
        src = (
            '// comment mentioning fn main() stays intact\n'
            'fn append_tag(s: &mut String, tag: &str) {\n'
            '    s.push_str(tag);\n'
            '}\n'
            'fn main() {\n'
            '    println!("fn main() inside string stays intact");\n'
            '}\n'
        )
        checks = [
            {"name": "append_tag", "args": ["rust", "!"], "argModes": ["mut_string", "auto"], "returnsMutArg0": True, "expected": "rust!"},
            {"name": "sum_pos", "args": [[]], "argModes": ["empty_i32_slice"], "expected": 0},
        ]
        harness = rust_bridge.build_rust_check_harness(src, checks)
        self.assertIn("// comment mentioning fn main() stays intact", harness)
        self.assertIn('println!("fn main() inside string stays intact");', harness)
        self.assertEqual(harness.count("fn __codestep_user_main()"), 1)
        self.assertEqual(len(re.findall(r"^fn main\(\)", harness, flags=re.M)), 1)
        self.assertIn('let mut __mut_arg_0_0 = String::from("rust");', harness)
        self.assertIn("append_tag(&mut __mut_arg_0_0, \"!\");", harness)
        self.assertIn("&([] as [i32; 0])", harness)

    def test_missing_rustc_graceful_guidance_and_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "main.rs"
            script.write_text('fn main() { println!("Hello, Rust!"); }\n', encoding="utf-8")
            missing_rt = {"available": False, "path": "", "mode": "missing", "label": "rustc 미설치"}
            question = {
                "id": "rust-hello-4",
                "type": "code",
                "lang": "rust",
                "prompt": "Hello, Rust!를 출력해 보세요.",
                "expected": "Hello, Rust!\n",
            }
            res = verify_workspace_question(Path(folder), script, question, missing_rt)
            self.assertFalse(res["ok"])
            self.assertFalse(res["passed"])
            self.assertTrue(res.get("missingCompiler"))
            self.assertEqual(res["runtimeMode"], "missing-rustc")
            self.assertIn("Rustlang.Rustup", res["error"])
            self.assertFalse(res["checks"][0]["ok"])

            with mock.patch("rust_bridge._candidate_rustcs", return_value=[(Path(folder) / "no_rustc.exe", "custom")]):
                probed = rust_bridge.discover_rust_runtime(str(Path(folder) / "no_rustc.exe"), refresh=True)
                self.assertFalse(probed["available"])

    def test_mocked_rustc_execution_and_function_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_rustc = root / "rustc.exe"
            fake_rustc.write_text("", encoding="utf-8")
            script = root / "main.rs"
            script.write_text(
                'fn add_double(a: i32, b: i32) -> i32 { (a + b) * 2 }\n'
                'fn main() { println!("{}", add_double(3, 7)); }\n',
                encoding="utf-8",
            )
            question = {
                "id": "rust-functions-4",
                "type": "code",
                "lang": "rust",
                "prompt": "add_double 함수를 만들고 20을 출력하세요.",
                "expected": "20\n",
                "functionChecks": [
                    {"name": "add_double", "args": [3, 7], "expected": 20},
                    {"name": "add_double", "args": [4, 1], "expected": 10},
                ],
            }
            runtime = {"available": True, "path": str(fake_rustc), "version": "1.82.0", "label": "Rust 1.82.0"}

            def fake_run(cmd, **kwargs):
                exe = str(cmd[0])
                if exe == str(fake_rustc):
                    self.assertIn(str(root), kwargs["env"]["PATH"])
                    out_idx = cmd.index("-o") + 1
                    Path(cmd[out_idx]).write_bytes(b"fake-exe")
                    return _FakeProc(0, "", "")
                if Path(exe).name == "main.exe":
                    return _FakeProc(0, "20\n", "")
                if Path(exe).name == "check.exe":
                    return _FakeProc(0, "__CODESTEP_CHK__:0:20\n__CODESTEP_CHK__:1:10\n", "")
                return _FakeProc(1, "", "unexpected call")

            with _fake_toolchain(fake_run):
                verified = verify_workspace_question(root, script, question, runtime, isolated=True)
            self.assertTrue(verified["ok"], verified)
            self.assertTrue(verified["passed"], verified)
            self.assertEqual(verified["runtimeMode"], "rustc")
            self.assertEqual(verified["output"], "20\n")
            self.assertEqual(len(verified["checks"]), 4)
            self.assertTrue(all(item["ok"] for item in verified["checks"]))

            def fake_run_compile_error(cmd, **kwargs):
                if str(cmd[0]) == str(fake_rustc):
                    return _FakeProc(1, "", "error[E0308]: mismatched types\n --> main.rs:1:40\n")
                return _FakeProc(1, "", "")

            with _fake_toolchain(fake_run_compile_error):
                failed = verify_workspace_question(root, script, question, runtime, isolated=True)
            self.assertFalse(failed["ok"])
            self.assertFalse(failed["passed"])
            self.assertIn("기대한 타입", failed["error"])

    def test_beginner_rust_diagnostics_and_panic_messages(self):
        err_fmt, line_fmt = rust_bridge.translate_rust_error(
            "error[E0277]: `Vec<i32>` doesn't implement `std::fmt::Display` (cannot be formatted with the default formatter)\n --> main.rs:3:17\n"
        )
        self.assertEqual(line_fmt, 3)
        self.assertIn("{:?}", err_fmt)
        self.assertIn("#[derive(Debug)]", err_fmt)

        err_type, _ = rust_bridge.translate_rust_error(
            "error[E0412]: cannot find type `HashMap` in this scope\n --> main.rs:2:12\n"
        )
        self.assertIn("use std::collections", err_type)

        err_chain, _ = rust_bridge.translate_rust_error(
            "error: comparison operators cannot be chained\n --> main.rs:4:10\n"
        )
        self.assertIn("&&", err_chain)

        err_move_ref, _ = rust_bridge.translate_rust_error(
            "error[E0507]: cannot move out of `*x` which is behind a shared reference\n --> main.rs:5:9\n"
        )
        self.assertIn("빌린 참조", err_move_ref)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_rustc = root / "rustc.exe"
            fake_rustc.write_bytes(b"fake")
            script = root / "main.rs"
            script.write_text('fn main() { let v = vec![1]; println!("{}", v[5]); }\n', encoding="utf-8")

            def fake_panic(cmd, **kwargs):
                exe = str(cmd[0])
                if exe == str(fake_rustc):
                    out_idx = cmd.index("-o") + 1
                    Path(cmd[out_idx]).write_bytes(b"fake-exe")
                    return _FakeProc(0, "", "")
                return _FakeProc(101, "", "thread 'main' panicked at 'index out of bounds: the len is 1 but the index is 5'")

            with _fake_toolchain(fake_panic):
                panicked = rust_bridge.run_rust_script(script, root, rust_path=str(fake_rustc))
            self.assertFalse(panicked["ok"])
            self.assertIn("[실행 중 패닉 힌트]", panicked["error"])
            self.assertIn("len() - 1", panicked["error"])

    def test_rust_function_check_sample_formatting(self):
        mut_sample = CodeStepApp._format_check_sample(
            {
                "name": "append_tag",
                "args": ["rust", "!"],
                "argModes": ["mut_string", "auto"],
                "returnsMutArg0": True,
                "expected": "rust!",
            },
            lang="rust",
        )
        self.assertEqual(mut_sample, 'append_tag(&mut String::from("rust"), "!")  ->  "rust!"')

        tuple_sample = CodeStepApp._format_check_sample(
            {"name": "min_max", "args": [[4, 9, 2]], "expectedDebug": "(2, 9)", "expected": [2, 9]},
            lang="rust",
        )
        self.assertEqual(tuple_sample, "min_max(&[4, 9, 2])  ->  (2, 9)")

        empty_sample = CodeStepApp._format_check_sample(
            {"name": "has_pos", "args": [[]], "argModes": ["empty_i32_slice"], "expected": False},
            lang="rust",
        )
        self.assertEqual(empty_sample, "has_pos(&[])  ->  false")

    def test_e0596_precedence_and_updated_practical_questions(self):
        from learning import QUESTIONS

        err_mut, line_mut = rust_bridge.translate_rust_error(
            "error[E0596]: cannot borrow `x` as mutable, as it is not declared as mutable\n --> main.rs:3:5\n"
        )
        self.assertEqual(line_mut, 3)
        self.assertIn("let mut", err_mut)
        self.assertNotIn("가변 참조가 겹쳤어요", err_mut)

        qmap = {q["id"]: q for q in QUESTIONS}
        types_q = qmap["rust-types-4"]
        self.assertNotIn("functionChecks", types_q)

        param_q = qmap["rust-exam-parametric-4"]
        empty_chk = param_q["functionChecks"][-1]
        self.assertEqual(empty_chk["argModes"][0], "empty_i32_slice")
        self.assertEqual(CodeStepApp._format_check_sample(empty_chk, lang="rust"), "min_capacity(&[], 3)  ->  0")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_rustc = root / "rustc.exe"
            fake_rustc.write_bytes(b"fake")
            runtime = {"available": True, "path": str(fake_rustc), "version": "1.82.0", "label": "Rust 1.82.0"}

            def fake_run(cmd, **kwargs):
                exe = str(cmd[0])
                if exe == str(fake_rustc):
                    out_idx = cmd.index("-o") + 1
                    Path(cmd[out_idx]).write_bytes(b"fake-exe")
                    return _FakeProc(0, "", "")
                if Path(exe).name == "main.exe":
                    src = (root / "main.rs").read_text(encoding="utf-8")
                    out = "3.5\nscore=95\n" if "score" in src else "6\n"
                    return _FakeProc(0, out, "")
                if Path(exe).name == "check.exe":
                    return _FakeProc(
                        0,
                        "__CODESTEP_CHK__:0:15\n__CODESTEP_CHK__:1:6\n__CODESTEP_CHK__:2:15\n__CODESTEP_CHK__:3:0\n",
                        "",
                    )
                return _FakeProc(1, "", "unexpected call")

            script = root / "main.rs"
            script.write_text(types_q["solution"], encoding="utf-8")
            with _fake_toolchain(fake_run):
                res_types = verify_workspace_question(root, script, types_q, runtime, isolated=True)
            self.assertTrue(res_types["passed"], res_types)
            self.assertEqual(len(res_types["checks"]), 2)

            script.write_text(param_q["solution"], encoding="utf-8")
            with _fake_toolchain(fake_run):
                res_param = verify_workspace_question(root, script, param_q, runtime, isolated=True)
            self.assertTrue(res_param["passed"], res_param)
            self.assertEqual(len(res_param["checks"]), 6)


class RustBeginnerHintTests(unittest.TestCase):
    def test_specific_hints_come_first(self):
        cases = [
            ("error[E0423]: cannot find function `println` in this scope\n --> main.rs:2:5\n", "느낌표"),
            ("error[E0277]: cannot add `f64` to `i32`\n --> main.rs:4:22\n", "as f64"),
            ("error[E0004]: non-exhaustive patterns: `3_i32..=i32::MAX` not covered\n --> main.rs:3:11\n", "_ =>"),
            ("error[E0308]: mismatched types\n --> main.rs:3:8\n  |\n3 |     if n {\n  |        ^ expected `bool`, found integer\n", "bool"),
            ("error[E0308]: `if` and `else` have incompatible types\n --> main.rs:3:50\n", "if`와 `else"),
            ("error: expected one of `:`, `@`, or `|`, found `)`\n --> main.rs:1:12\n", "n: i32"),
            ("error[E0277]: `Vec<{integer}>` doesn't implement `std::fmt::Display`\n --> main.rs:3:20\n", "{:?}"),
        ]
        for stderr, expected in cases:
            with self.subTest(stderr=stderr.splitlines()[0]):
                message, _ = rust_bridge.translate_rust_error(stderr)
                first_hint = message.split("[힌트]", 1)[1]
                self.assertIn(expected, first_hint[:80])


class RustExecutionSafetyTests(unittest.TestCase):
    def test_char_and_raw_string_literals_do_not_hide_main(self):
        # '"' used to be read as the start of a string, so `fn main` was never renamed and the
        # function-check build failed with "main defined twice" even for a correct answer.
        sources = [
            "fn is_quote(c: char) -> bool {\n    c == '\"'\n}\nfn main() {\n    println!(\"{}\", is_quote('a'));\n}\n",
            "fn open(c: char) -> bool { c == '{' }\nfn main() { println!(\"{}\", open('{')); }\n",
            "fn esc() -> char { '\\'' }\nfn main() { println!(\"{}\", esc()); }\n",
            "fn raw() -> &'static str { r#\"say \"hi\" {\"# }\nfn main() { println!(\"{}\", raw()); }\n",
            "fn first<'a>(s: &'a str) -> &'a str { &s[..1] }\nfn main() { println!(\"{}\", first(\"ab\")); }\n",
        ]
        for src in sources:
            with self.subTest(src=src):
                renamed = rust_bridge._replace_fn_main(src)
                self.assertIn("fn __codestep_user_main()", renamed)
                self.assertEqual(renamed.replace("__codestep_user_main", "main"), src)

    def test_endless_output_is_stopped_and_partial_output_is_kept(self):
        started = time.perf_counter()
        flood = rust_bridge._run_exe([sys.executable, "-c", "while True: print('반복 출력 0123456789' * 4)"], timeout=10)
        self.assertTrue(flood.overflow)
        self.assertFalse(flood.timed_out)
        self.assertLessEqual(len(flood.stdout), rust_bridge.MAX_OUTPUT_CHARS)
        self.assertLess(time.perf_counter() - started, 8, "the flood must be cut off long before the timeout")

        slow = rust_bridge._run_exe([sys.executable, "-c", "import time; print('first line', flush=True); time.sleep(30)"], timeout=2)
        self.assertTrue(slow.timed_out)
        self.assertEqual(slow.stdout, "first line\n")

        echo = rust_bridge._run_exe([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], input="한글 입력\n둘째 줄\n")
        self.assertEqual((echo.returncode, echo.stdout), (0, "한글 입력\n둘째 줄\n"))

    def test_cp949_rust_source_is_compiled_as_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_rustc = root / "rustc.exe"
            fake_rustc.write_bytes(b"fake")
            script = root / "main.rs"
            script.write_bytes('fn main() { println!("안녕"); }\n'.encode("cp949"))
            seen = {}

            def fake(cmd, **kwargs):
                if str(cmd[0]) == str(fake_rustc):
                    seen["source"] = Path(cmd[cmd.index("-o") - 1]).read_text(encoding="utf-8")
                    Path(cmd[cmd.index("-o") + 1]).write_bytes(b"fake-exe")
                    return _FakeProc(0, "", "")
                return _FakeProc(0, "안녕\n", "")

            with _fake_toolchain(fake):
                result = rust_bridge.run_rust_script(script, root, rust_path=str(fake_rustc))
            self.assertTrue(result["ok"], result)
            self.assertIn('println!("안녕")', seen["source"])

    @unittest.skipUnless(rust_bridge.discover_rust_runtime()["available"], "rustc is not installed")
    def test_real_rustc_endless_print_reports_a_beginner_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "main.rs"
            script.write_text('fn main() {\n    loop {\n        println!("끝나지 않는 출력");\n    }\n}\n', encoding="utf-8")
            result = rust_bridge.run_rust_script(script, root, rust_path=rust_bridge.discover_rust_runtime()["path"])
            self.assertFalse(result["ok"])
            self.assertIn("출력이 너무 길어", result["error"])
            self.assertIn("끝나지 않는 출력", result["output"])


@unittest.skipUnless(os.name == "nt", "cmd.exe terminal launch is Windows only")
class TerminalCommandTests(unittest.TestCase):
    def _run(self, command, cwd):
        proc = subprocess.run(command, cwd=str(cwd), capture_output=True, timeout=120)
        # The program prints UTF-8, but cmd's own echo lines follow the console code page. Without a
        # console (e.g. tests started from Git Bash) "chcp 65001" has no effect and they come out as
        # cp949, so each line is decoded on its own.
        def decode(raw):
            lines = []
            for line in raw.splitlines():
                try:
                    lines.append(line.decode("utf-8"))
                except UnicodeDecodeError:
                    lines.append(line.decode("cp949", "replace"))
            return "\n".join(lines)
        return decode(proc.stdout) + "\n" + decode(proc.stderr)

    def test_python_terminal_command_runs_paths_with_spaces_and_symbols(self):
        # The old command list was escaped by subprocess as \"...\" which cmd.exe rejects, so the
        # "터미널 실행" button only ever showed "is not recognized as an internal or external command".
        from python_bridge import python_terminal_command
        with tempfile.TemporaryDirectory(prefix="코드 (연습) & 폴더 ") as tmp:
            work = Path(tmp)
            script = work / "main.py"
            script.write_text("import sys\nprint('터미널 출력')\nsys.exit(3)\n", encoding="utf-8")
            text = self._run(python_terminal_command(script, work, {"path": sys.executable, "version": "3"}, wait_for_key=False), work)
            self.assertIn("터미널 출력", text)
            self.assertIn("[종료 코드 3", text)
            self.assertNotIn("is not recognized", text)

    @unittest.skipUnless(rust_bridge.discover_rust_runtime()["available"], "rustc is not installed")
    def test_rust_terminal_command_compiles_and_runs(self):
        runtime = rust_bridge.discover_rust_runtime()
        with tempfile.TemporaryDirectory(prefix="러스트 (연습) ") as tmp:
            work = Path(tmp)
            script = work / "main.rs"
            script.write_text('fn main() { println!("러스트 터미널"); std::process::exit(4); }\n', encoding="utf-8")
            command = rust_bridge.rust_terminal_command(script, work, runtime, work / "out.exe", wait_for_key=False)
            text = self._run(command, work)
            self.assertIn("러스트 터미널", text)
            self.assertIn("[종료 코드 4", text)


if __name__ == "__main__":
    unittest.main()
