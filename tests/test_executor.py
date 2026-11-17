import tempfile
import unittest
from pathlib import Path
from code_executor import run_code, run_workspace_script


class AppFolderIsolationTests(unittest.TestCase):
    def test_files_next_to_runner_are_not_imported_by_the_worker(self):
        # Inside the EXE, runner.py sits next to the bundled Python 3.12 extension modules. A PC's
        # Python 3.15 imported that _ctypes.pyd and every coding question failed. A trap module next
        # to runner.py reproduces the same situation on any Python version.
        import sys
        from unittest.mock import patch
        import code_executor

        with tempfile.TemporaryDirectory() as app_dir, tempfile.TemporaryDirectory() as work:
            app = Path(app_dir)
            app.joinpath("runner.py").write_bytes(Path(code_executor.ROOT, "runner.py").read_bytes())
            app.joinpath("ctypes.py").write_text("raise ImportError('app folder was on sys.path')\n", encoding="utf-8")
            script = Path(work) / "main.py"
            script.write_text('import ctypes\nprint("Hello, Python!")\n', encoding="utf-8")
            with patch.object(code_executor, "ROOT", app):
                for python_path in (sys.executable, None):
                    with self.subTest(python_path=python_path):
                        result = run_workspace_script(script, work, python_path=python_path)
                        self.assertTrue(result["ok"], result)
                        self.assertEqual(result["output"], "Hello, Python!\n")


class BeginnerHintTests(unittest.TestCase):
    """Hints for mistakes beginners really make; several used to point at the wrong cause."""

    def check(self, code, *expected, stdin=""):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "main.py"
            script.write_text(code, encoding="utf-8")
            result = run_workspace_script(script, td, stdin=stdin)
        self.assertFalse(result["ok"], result)
        for text in expected:
            self.assertIn(text, result["error"])
        return result["error"]

    def test_syntax_mistakes(self):
        self.check("x = 1\nif x > 2:\n    pass\nelse if x > 0:\n    pass", "elif")
        self.check("print(\u201c안녕\u201d)", "전각")
        self.check("1st = 10", "글자로 시작")
        self.check("for i in range(3):\n    pass\nbreak", "반복문 안")
        self.check('print "hi"', 'print("안녕")')

    def test_runtime_mistakes(self):
        self.check("def add(a, b):\n    return a + b\nadd(1)", "모자라요")
        self.check("def hi(name):\n    pass\nhi(1, 2)", "너무 많아요")
        self.check('print("나이: " + 15)', "쉼표")
        self.check('print = "a"\nprint(1)', "함수 이름과 겹치지")
        self.check('print(int("열"))', "값의 형식", "float()")
        message = self.check('open("m.txt", "w").close()\nwith open("m.txt") as f:\n    f.write("x")', "\"a\"")
        self.assertIn("UnsupportedOperation", message)


class RunnerTests(unittest.TestCase):
    def test_korean_input_functions_and_collections(self):
        code = 'def double(n):\n    return n * 2\nvalues = [double(n) for n in range(1, 4)]\nprint("안녕", input())\nprint(values)'
        result = run_code(code, '파이썬\n')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['output'], '안녕 파이썬\n[2, 4, 6]\n')

    def test_import_files_introspection_and_execution_are_blocked(self):
        for code in ['import os', 'open("example.txt", "w")', 'print((1).__class__)', '__import__("os")', 'exec("print(1)")', 'eval("1 + 1")', 'print("{0.__class__}".format(1))']:
            with self.subTest(code=code):
                self.assertFalse(run_code(code)['ok'])

    def test_errors_explain_the_line_without_host_paths(self):
        result = run_code('x = 1\nprint(x / 0)')
        self.assertFalse(result['ok'])
        self.assertEqual(result['line'], 2)
        self.assertIn('0으로', result['error'])
        self.assertNotIn(str(Path.cwd()), result['error'])
        self.assertFalse(run_code('if True\n    print(1)')['ok'])

    def test_output_is_bounded(self):
        result = run_code('for n in range(100000):\n    print("abcdefghijklmnop")')
        self.assertFalse(result['ok'])
        self.assertLessEqual(len(result['output']), 12000)

    def test_infinite_loop_times_out(self):
        result = run_code('while True:\n    pass')
        self.assertFalse(result['ok'])
        self.assertLess(result['elapsed'], 7500)

    def test_excessive_allocation_is_contained(self):
        result = run_code('x = "a" * 1000000000')
        self.assertFalse(result['ok'])
        self.assertTrue(run_code('print(2 + 2)')['ok'])

    def test_input_validation(self):
        self.assertFalse(run_code(123)['ok'])
        self.assertFalse(run_code('')['ok'])
        self.assertFalse(run_code('x' * 8001)['ok'])
        result = run_code('input()')
        self.assertFalse(result['ok'])
        self.assertIn('입력값', result['error'])
        korean = run_code('text = "' + '가' * 4500 + '"\nprint(len(text))')
        self.assertTrue(korean['ok'], korean)
        self.assertEqual(korean['output'], '4500\n')

    def test_korean_syntax_and_runtime_error_hints(self):
        missing_colon = run_code('if True\n    print(1)')
        self.assertFalse(missing_colon['ok'])
        self.assertEqual(missing_colon['line'], 1)
        self.assertIn('콜론', missing_colon['error'])

        missing_indent = run_code('if True:\nprint(1)')
        self.assertFalse(missing_indent['ok'])
        self.assertIn('들여써야', missing_indent['error'])

        tab_mix = run_code('if True:\n        print(1)\n\tprint(2)')
        self.assertFalse(tab_mix['ok'])
        self.assertIn('탭(Tab)', tab_mix['error'])

        unindent_err = run_code('if True:\n\tprint(1)\n    print(2)')
        self.assertFalse(unindent_err['ok'])
        self.assertIn('들여쓰기 칸 수', unindent_err['error'])

        value_err = run_code('print(int("abc"))')
        self.assertFalse(value_err['ok'])
        self.assertIn('ValueError', value_err['error'])
        self.assertIn('값의 형식', value_err['error'])

        attr_err = run_code('nums = [1, 2]\nnums.sort().append(3)')
        self.assertFalse(attr_err['ok'])
        self.assertIn('AttributeError', attr_err['error'])
        self.assertIn('해당 자료형', attr_err['error'])

        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            script = ws / 'solution.py'
            script.write_text('if x = 1:\n    pass\n', encoding='utf-8')
            ws_syn = run_workspace_script(script, ws)
            self.assertFalse(ws_syn['ok'])
            self.assertIn('==', ws_syn['error'])

            script.write_text('print(int("oops"))\n', encoding='utf-8')
            ws_val = run_workspace_script(script, ws)
            self.assertFalse(ws_val['ok'])
            self.assertIn('ValueError', ws_val['error'])
            self.assertIn('값의 형식', ws_val['error'])


