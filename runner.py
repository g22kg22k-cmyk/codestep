"""Restricted educational CPython worker; always run in a child process."""
import ast
import io
import json
import re
import sys

MAX_OUTPUT = 12_000
MEMORY_LIMIT = 160 * 1024 * 1024
WINDOWS_JOB = None


class PracticeError(Exception):
    pass


def limit_memory():
    global WINDOWS_JOB
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IOCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IOCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        WINDOWS_JOB = kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x100 | 0x8
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        limits.ProcessMemoryLimit = MEMORY_LIMIT
        if not WINDOWS_JOB or not kernel.SetInformationJobObject(WINDOWS_JOB, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(WINDOWS_JOB, kernel.GetCurrentProcess()):
            raise PracticeError("코드 실행 보호장치를 준비하지 못했어요. 앱을 다시 시작해 주세요.")
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Name, ast.Constant,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If, ast.IfExp,
    ast.For, ast.While, ast.Break, ast.Continue, ast.Pass, ast.Call,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.keyword,
    ast.Attribute, ast.JoinedStr, ast.FormattedValue,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension,
    ast.Try, ast.ExceptHandler, ast.Raise,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)
METHODS = {"append", "pop", "remove", "sort", "reverse", "count", "index", "copy", "clear", "extend", "insert", "keys", "values", "items", "get", "update", "setdefault", "upper", "lower", "strip", "lstrip", "rstrip", "replace", "split", "join", "startswith", "endswith", "find", "capitalize", "title", "isalpha", "isdigit", "isalnum"}


def validate(code):
    tree = ast.parse(code, filename="<연습장>", mode="exec")
    nodes = list(ast.walk(tree))
    if len(nodes) > 1_500:
        raise PracticeError("코드가 너무 복잡해요. 작은 부분으로 나누어 실행해 주세요.")
    for node in nodes:
        if not isinstance(node, ALLOWED_NODES):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                raise PracticeError("이 연습장은 외부 모듈을 불러오지 않아요. 기본 파이썬 문법으로 연습해 주세요.")
            raise PracticeError(f"이 연습장에서는 {type(node).__name__} 문법을 지원하지 않아요.")
        names = [getattr(node, key, "") for key in ("id", "name", "arg")]
        if any(isinstance(name, str) and name.startswith("_") for name in names):
            raise PracticeError("밑줄로 시작하는 내부 이름은 이 연습장에서 사용할 수 없어요.")
        if isinstance(node, ast.Attribute) and node.attr not in METHODS:
            raise PracticeError("이 메서드 또는 속성은 학습용 연습장에서 지원하지 않아요.")
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            raise PracticeError("이 연습장에서는 데코레이터를 지원하지 않아요.")
    return tree


class Output(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > MAX_OUTPUT:
            raise PracticeError("출력이 12,000자를 넘었어요. 출력 횟수를 줄여 주세요.")
        return super().write(value)


def execute(code, stdin=""):
    output = Output()
    source_input = io.StringIO(stdin)

    def practice_print(*values, sep=" ", end="\n"):
        print(*values, sep=sep, end=end, file=output)

    def practice_input(prompt=""):
        if prompt:
            output.write(str(prompt))
        value = source_input.readline()
        if value == "":
            raise PracticeError("입력값이 부족해요. ‘표준 입력(stdin)’ 칸에 input()이 읽을 값을 한 줄씩 넣어 주세요.")
        return value.rstrip("\r\n")

    safe = {"print": practice_print, "input": practice_input, "len": len, "range": range, "int": int, "float": float, "str": str, "bool": bool, "list": list, "tuple": tuple, "dict": dict, "set": set, "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "sorted": sorted, "enumerate": enumerate, "zip": zip, "reversed": reversed, "all": all, "any": any, "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError, "IndexError": IndexError, "KeyError": KeyError, "ZeroDivisionError": ZeroDivisionError}
    try:
        tree = validate(code)
        namespace = {"__builtins__": safe}
        exec(compile(tree, "<연습장>", "exec"), namespace, namespace)
        return {"ok": True, "output": output.getvalue(), "error": ""}
    except SyntaxError as error:
        return {"ok": False, "output": output.getvalue(), "error": _format_python_syntax_error(error), "line": error.lineno}
    except BaseException as error:
        line = None
        tb = error.__traceback__
        while tb:
            if tb.tb_frame.f_code.co_filename == "<연습장>":
                line = tb.tb_lineno
            tb = tb.tb_next
        if isinstance(error, PracticeError):
            message = str(error)
        else:
            message = f"{type(error).__name__}: {_runtime_hint(error) or str(error)}"
        return {"ok": False, "output": output.getvalue(), "error": (f"{line}번째 줄: " if line else "") + message, "line": line}


class BoundedTextBuffer(io.StringIO):
    def __init__(self, limit=64_000):
        super().__init__()
        self.limit = limit

    def write(self, value):
        if self.tell() + len(value) > self.limit:
            raise PracticeError("출력이 너무 길어요(최대 64,000자). 반복 출력을 줄여 주세요.")
        return super().write(value)


def _extract_script_line(tb, target_name):
    line = None
    while tb:
        if tb.tb_frame.f_code.co_filename == target_name:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _matches_expected(actual, expected, tolerance=None):
    if tolerance is not None and isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(actual - expected) <= tolerance
    return actual == expected


def _format_call_args(args, kwargs):
    parts = [repr(a) for a in args]
    parts.extend(f"{k}={v!r}" for k, v in kwargs.items())
    return ", ".join(parts)


def _run_function_checks(namespace, checks):
    import types

    results = []
    for item in checks or []:
        cls_name = item.get("className")
        fn_name = item.get("name") or (f"{cls_name}.{item.get('method', '')}" if cls_name else "")
        args = item.get("args", [])
        kwargs = item.get("kwargs") or {}
        expected = item.get("expected")
        tolerance = item.get("tolerance")
        if cls_name:
            cls = namespace.get(cls_name)
            if not isinstance(cls, type):
                results.append({"name": fn_name, "ok": False, "detail": f"'{cls_name}' 클래스를 찾지 못했어요."})
                continue
            base_name = item.get("baseClassName")
            if base_name:
                base_cls = namespace.get(base_name)
                if not isinstance(base_cls, type) or not issubclass(cls, base_cls):
                    results.append({"name": fn_name, "ok": False, "detail": f"'{cls_name}' 클래스가 '{base_name}'을 상속받아야 해요."})
                    continue
            init_args = item.get("initArgs", [])
            method_name = item.get("method", "")
            method_args = item.get("methodArgs", [])
            try:
                instance = cls(*init_args)
                method_fn = getattr(instance, method_name, None)
                if not callable(method_fn):
                    results.append({"name": fn_name, "ok": False, "detail": f"'{cls_name}.{method_name}()' 메서드를 찾지 못했어요."})
                    continue
                actual = method_fn(*method_args)
                passed = _matches_expected(actual, expected, tolerance)
                call_desc = f"{cls_name}({_format_call_args(init_args, {})}).{method_name}({_format_call_args(method_args, kwargs)})"
                detail = f"{call_desc} -> {actual!r}"
                if not passed:
                    detail += f" (기댓값: {expected!r})"
                results.append({"name": fn_name, "ok": passed, "detail": detail})
            except BaseException as error:
                results.append({"name": fn_name, "ok": False, "detail": f"{fn_name} 실행 오류: {type(error).__name__}: {error}"})
            continue

        fn = namespace.get(fn_name)
        if not callable(fn):
            results.append({"name": fn_name, "ok": False, "detail": f"'{fn_name}' 함수를 찾지 못했어요."})
            continue
        try:
            actual = fn(*args, **kwargs)
            if item.get("isGenerator"):
                if not isinstance(actual, types.GeneratorType):
                    results.append({"name": fn_name, "ok": False, "detail": f"'{fn_name}()'는 return list 대신 yield 제너레이터 함수로 작성해야 해요."})
                    continue
                actual = list(actual)
            passed = _matches_expected(actual, expected, tolerance)
            arg_text = _format_call_args(args, kwargs)
            detail = f"{fn_name}({arg_text}) -> {actual!r}"
            if not passed:
                detail += f" (기댓값: {expected!r})"
            results.append({"name": fn_name, "ok": passed, "detail": detail})
        except BaseException as error:
            results.append({"name": fn_name, "ok": False, "detail": f"{fn_name} 실행 오류: {type(error).__name__}: {error}"})
    return results


def execute_workspace_file(script_path, work_dir, stdin="", function_checks=None):
    import os
    from pathlib import Path

    script = Path(script_path).resolve()
    workspace = Path(work_dir).resolve()
    if not script.is_file():
        return {"ok": False, "output": "", "error": "실행할 파이썬 파일을 찾지 못했어요.", "functionResults": []}
    try:
        source = script.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = script.read_text(encoding="cp949")

    os.chdir(workspace)
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))

    stdout_buf = BoundedTextBuffer()
    stderr_buf = BoundedTextBuffer()
    old_stdin, old_stdout, old_stderr, old_argv = sys.stdin, sys.stdout, sys.stderr, sys.argv
    sys.stdin = io.StringIO(stdin)
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    sys.argv = [str(script)]
    target_name = str(script)
    namespace = {"__name__": "__main__", "__file__": target_name, "__package__": None}
    try:
        compiled = compile(source, target_name, "exec")
        exec(compiled, namespace, namespace)
        func_results = _run_function_checks(namespace, function_checks)
        err_text = stderr_buf.getvalue()
        return {"ok": True, "output": stdout_buf.getvalue(), "error": err_text, "functionResults": func_results}
    except SystemExit as exit_err:
        code_val = exit_err.code
        ok = code_val in (None, 0)
        func_results = _run_function_checks(namespace, function_checks) if ok else []
        msg = "" if ok else f"프로그램이 종료 코드 {code_val}(으)로 끝났어요."
        return {"ok": ok, "output": stdout_buf.getvalue(), "error": msg, "functionResults": func_results}
    except SyntaxError as error:
        return {"ok": False, "output": stdout_buf.getvalue(), "error": _format_python_syntax_error(error), "line": error.lineno, "functionResults": []}
    except BaseException as error:
        line = _extract_script_line(error.__traceback__, target_name)
        if isinstance(error, PracticeError):
            message = str(error)
        else:
            hint = _runtime_hint(error)
            message = f"{type(error).__name__}: {error}" + (f" ({hint})" if hint else "")
        return {"ok": False, "output": stdout_buf.getvalue(), "error": (f"{line}번째 줄: " if line else "") + message, "line": line, "functionResults": []}
    finally:
        sys.stdin, sys.stdout, sys.stderr, sys.argv = old_stdin, old_stdout, old_stderr, old_argv


def worker_result(payload):
    sys.setrecursionlimit(250)
    try:
        limit_memory()
        return execute(payload["code"], payload.get("stdin", ""))
    except BaseException as error:
        return {"ok": False, "output": "",
                "error": f"코드 실행 보호장치를 준비하지 못했어요 ({type(error).__name__}: {error}). 앱을 다시 시작해 주세요."}


_PYTHON_RUNTIME_HINTS = {
    "NameError": "변수나 함수 이름 오타를 확인하고, 사용하기 전에 먼저 값을 저장(=)하거나 정의했는지 살펴보세요.",
    "UnboundLocalError": "함수 안에서 지역 변수를 대입(=)하기 전에 먼저 읽으려고 했어요. 함수 위쪽에서 초기값을 정하거나 global 키워드를 확인해 주세요.",
    "TypeError": "자료형(문자열·숫자·리스트 등)이 서로 맞지 않거나 함수 인자 개수가 달라요. 문자열과 숫자를 +로 잇기 전에 int()·str() 변환을 확인해 보세요.",
    "ValueError": "값의 형식이나 개수가 올바르지 않아요. 예: int('abc')처럼 숫자가 아닌 글자를 바꾸려 했거나, 언패킹 변수 개수가 다를 수 있어요.",
    "IndexError": "인덱스는 0부터 시작해요. 리스트나 문자열 길이를 벗어나지 않았는지 확인해 주세요.",
    "KeyError": "딕셔너리에 해당 키가 없어요. 키 오타를 확인하거나 d.get(키, 기본값)을 써 보세요.",
    "AttributeError": "해당 자료형에는 그런 메서드나 속성이 없어요. 변수에 예상과 다른 값(예: None)이 들어 있지 않은지 확인해 주세요.",
    "ZeroDivisionError": "숫자를 0으로 나눌 수 없어요. 나눗셈(/, //, %) 전 분모가 0인지 확인해 주세요.",
    "RecursionError": "함수가 스스로를 너무 많이 호출해 멈췄어요. 재귀가 끝나는 종료 조건(return)을 확인해 주세요.",
    "MemoryError": "메모리 한도를 넘었어요. 데이터 크기나 반복 횟수를 줄여 주세요.",
    "EOFError": "입력값이 부족해요. ‘표준 입력(stdin)’ 칸에 input()이 읽을 값을 한 줄씩 넣어 주세요 (레슨 실기에서는 준비된 입력값만큼만 input()을 호출하세요).",
    "FileNotFoundError": "열려는 파일이 작업 폴더에 있는지, 파일 이름과 철자가 정확한지 확인해 주세요.",
    "ModuleNotFoundError": "불러오려는 모듈 이름이 맞는지(또는 설치되어 있는지) 확인해 주세요.",
    "ImportError": "모듈에서 가져오려는 이름(함수·클래스) 철자를 확인해 주세요.",
}


def _runtime_hint(error):
    """Korean hint for a runtime error. TypeError has several unrelated causes, so read its message."""
    name = type(error).__name__
    text = str(error)
    if name == "TypeError":
        if "required positional argument" in text:
            return "함수를 부를 때 넘긴 값이 모자라요. def 줄에 적은 매개변수 개수만큼 괄호 안에 값을 넣어 주세요."
        if " positional argument" in text and " were given" in text:
            return "함수를 부를 때 넘긴 값이 너무 많아요. def 줄에 적은 매개변수 개수와 맞춰 주세요."
        if "can only concatenate str" in text or "must be str, not" in text:
            return "문자열과 숫자는 +로 바로 이을 수 없어요. str(숫자)로 바꾸거나 print(\"나이:\", age)처럼 쉼표로 나눠 출력해 보세요."
        if "not callable" in text:
            return "함수가 아닌 값 뒤에 괄호 ()를 붙였어요. 변수 이름이 print·len·input 같은 함수 이름과 겹치지 않았는지 확인해 주세요."
        if "unsupported operand type" in text:
            return "서로 계산할 수 없는 자료형끼리 연산했어요. int()·float()·str()로 자료형을 맞춘 뒤 계산해 주세요."
    if name == "ValueError" and "invalid literal for int()" in text:
        return "값의 형식이 정수 모양이 아니에요. int()는 \"10\"처럼 숫자 모양인 글자만 바꿀 수 있고, 소수 모양(\"3.5\")은 float()을 써요."
    if name == "UnsupportedOperation":
        return "파일을 연 방식(모드)으로는 할 수 없는 작업이에요. 읽기는 open(이름, \"r\"), 새로 쓰기는 \"w\", 이어 쓰기는 \"a\"로 열어 주세요."
    if name == "AttributeError" and "NoneType" in text:
        return ("값이 None이라 해당 자료형의 메서드를 쓸 수 없어요. append()·sort()처럼 결과를 돌려주지 않는 메서드의 "
                "결과를 다시 변수에 넣지 않았는지 확인해 주세요.")
    return _PYTHON_RUNTIME_HINTS.get(name)


def _format_python_syntax_error(error):
    """Turn common Python SyntaxError/IndentationError messages into beginner-friendly Korean."""
    line = error.lineno or 1
    msg = error.msg or "문법 오류"
    low = msg.lower()
    source_line = error.text or ""
    if re.search(r"\belse\s+if\b", source_line):
        ko = "파이썬에서는 else if 대신 elif라고 써요. 예: elif score >= 60:"
    elif "invalid character" in low and re.search(r"[“”‘’，。：；（）]", source_line + msg):
        ko = "따옴표나 기호가 한글 자판의 전각 문자(“ ” ‘ ’ ， ：)로 입력됐어요. 영문 자판으로 바꿔 \" ' , : 를 다시 입력해 주세요."
    elif "invalid decimal literal" in low:
        ko = "숫자 바로 뒤에 글자를 붙여 쓸 수 없어요. 변수 이름은 1st 대신 first처럼 글자로 시작하고, 곱셈은 3 * x처럼 *를 써 주세요."
    elif "outside loop" in low or "not properly in loop" in low:
        ko = "break와 continue는 for나 while 반복문 안(들여쓴 부분)에서만 쓸 수 있어요."
    elif "'return' outside function" in low:
        ko = "return은 def로 만든 함수 안(들여쓴 부분)에서만 쓸 수 있어요."
    elif "missing parentheses in call to 'print'" in low:
        ko = "print 뒤에는 괄호가 필요해요. print \"안녕\"이 아니라 print(\"안녕\")처럼 써 주세요."
    elif isinstance(error, TabError) or "inconsistent use of tabs" in low:
        ko = "탭(Tab)과 스페이스(빈칸)가 섞여 있어요. 모두 스페이스 4칸으로 통일해 주세요."
    elif "unexpected indent" in low:
        ko = "필요 없는 앞쪽 들여쓰기(빈칸)가 들어갔어요. 앞줄 시작 위치에 맞춰 주세요."
    elif "expected an indented block" in low:
        ko = ":(콜론) 다음 줄은 스페이스 4칸만큼 들여써야 해요."
    elif "unindent does not match" in low:
        ko = "들여쓰기 칸 수가 위쪽 블록과 맞지 않아요. 스페이스 4칸 단위로 맞춰 주세요."
    elif "expected ':'" in low:
        ko = ":(콜론)이 빠졌어요. if / elif / else / for / while / def / class 줄 끝에 ':'을 붙여 주세요."
    elif "was never closed" in low or "unexpected eof" in low:
        ko = "괄호 ( ), [ ], { }의 열고 닫는 짝이 맞지 않아요."
    elif "unterminated string literal" in low or "eol while scanning string" in low:
        ko = "문자열 따옴표(\" 또는 ')가 닫히지 않았어요. 앞뒤 따옴표 종류가 같은지도 확인해 보세요."
    elif "maybe you meant '=='" in low or "cannot assign to" in low:
        ko = "값을 비교할 때는 '='가 아니라 '=='를 두 번 써야 해요."
    elif "forgot a comma" in low:
        ko = "항목 사이 쉼표(,)가 빠졌는지 확인해 주세요."
    else:
        ko = "괄호·따옴표·콜론(:)·들여쓰기(4칸)를 다시 확인해 주세요."
    return f"{line}번째 줄: {ko} ({msg})"


def execute_repl_line(code, work_dir, history=None):
    """Evaluate one interactive Python >>> prompt line with prior session history."""
    import os
    import traceback
    from pathlib import Path

    workspace = Path(work_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))

    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    namespace = {"__name__": "__main__", "__package__": None}
    try:
        sys.stdin = io.StringIO("")
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        for prev in history or []:
            if not isinstance(prev, str) or not prev.strip():
                continue
            try:
                exec(compile(prev, "<stdin>", "exec"), namespace, namespace)
            except BaseException:
                pass

        stdout_buf = BoundedTextBuffer()
        stderr_buf = BoundedTextBuffer()
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        text = (code or "").replace("\r\n", "\n")
        if not text.strip():
            return {"ok": True, "output": "", "error": "", "committed": False}

        compiled = compile(text, "<stdin>", "single")
        exec(compiled, namespace, namespace)
        return {
            "ok": True,
            "output": stdout_buf.getvalue(),
            "error": stderr_buf.getvalue(),
            "committed": True,
        }
    except SystemExit:
        return {
            "ok": True,
            "output": stdout_buf.getvalue() if "stdout_buf" in locals() else "",
            "error": "",
            "committed": False,
        }
    except SyntaxError as error:
        lines = traceback.format_exception_only(type(error), error)
        return {
            "ok": False,
            "output": stdout_buf.getvalue() if "stdout_buf" in locals() else "",
            "error": f'  File "<stdin>", line {error.lineno or 1}\n' + "".join(lines) + f"\n[힌트] {_format_python_syntax_error(error)}",
            "committed": False,
        }
    except BaseException as error:
        tb = error.__traceback__
        while tb is not None and tb.tb_next is not None and tb.tb_frame.f_code.co_filename != "<stdin>":
            tb = tb.tb_next
        lines = traceback.format_exception(type(error), error, tb)
        err_text = "".join(lines)
        hint = _runtime_hint(error)
        if hint:
            err_text = err_text.rstrip() + f"\n[힌트] {hint}\n"
        return {
            "ok": False,
            "output": stdout_buf.getvalue() if "stdout_buf" in locals() else "",
            "error": err_text,
            "committed": False,
        }
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr


def real_worker_result(payload):
    try:
        global MEMORY_LIMIT
        MEMORY_LIMIT = 256 * 1024 * 1024
        limit_memory()
        if payload.get("mode") == "repl":
            return execute_repl_line(
                payload.get("code", ""),
                payload["work_dir"],
                payload.get("history"),
            )
        return execute_workspace_file(
            payload["script_path"],
            payload["work_dir"],
            payload.get("stdin", ""),
            payload.get("function_checks"),
        )
    except BaseException as error:
        return {
            "ok": False, "output": "", "functionResults": [],
            "error": (f"파이썬 실행 환경을 준비하지 못했어요 (Python {sys.version.split()[0]} · {sys.executable} · "
                      f"{type(error).__name__}: {error}). 설정에서 'Python 자동 재검색'을 누르거나 다른 Python 경로를 지정해 보세요."),
        }


def file_worker(request_path, response_path):
    from pathlib import Path
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result = worker_result(payload)
    Path(response_path).write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")
    return 0


def real_file_worker(request_path, response_path):
    from pathlib import Path
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result = real_worker_result(payload)
    Path(response_path).write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--workspace":
        raise SystemExit(real_file_worker(sys.argv[2], sys.argv[3]))
    sys.stdin.reconfigure(encoding="utf-8")
    try:
        # JSON escapes can take up to twelve ASCII bytes per Unicode character.
        result = worker_result(json.loads(sys.stdin.read(160_000)))
    except (ValueError, KeyError, TypeError):
        result = {"ok": False, "output": "", "error": "실행할 코드를 읽지 못했어요."}
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
