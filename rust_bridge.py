"""Rust compiler (rustc) discovery, error localization, function harness, and execution bridge."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

_RUST_CACHE = {}
_RUST_CHAR_RE = re.compile(r"'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F_]{1,6}\}|.)|[^'\\\n])'")
_RUST_RAW_STRING_RE = re.compile(r'b?r(#*)"')

_RUST_DIAGNOSTICS = [
    # Specific beginner cases first: only the first two matching hints are shown.
    (re.compile(r"cannot find (?:function|value) `(?:println|print|eprintln|format|vec|panic|assert|assert_eq|write|writeln)`", re.I),
     "`println!`처럼 매크로 이름 뒤에는 느낌표(`!`)가 꼭 붙어요. `println!(\"...\")`로 고쳐 보세요."),
    (re.compile(r"cannot (?:add|subtract|multiply|divide) `[a-z0-9]+` (?:to|from|by) `[a-z0-9]+`", re.I),
     "정수(`i32`)와 실수(`f64`)처럼 타입이 다른 숫자끼리는 바로 계산할 수 없어요. `a as f64 + b`처럼 `as`로 타입을 맞춰 주세요."),
    (re.compile(r"expected one of `:`, `@`, or `\|`", re.I),
     "Rust 함수의 매개변수에는 `fn double(n: i32)`처럼 이름 뒤에 콜론(`:`)과 타입을 꼭 적어야 해요."),
    (re.compile(r"\bE0004\b|non-exhaustive patterns", re.I),
     "`match`가 가능한 모든 경우를 다루지 않았어요. 마지막 갈래로 `_ => ...`를 추가해 나머지 경우를 처리해 주세요."),
    (re.compile(r"expected `bool`, found", re.I),
     "Rust의 `if` 조건에는 `true`/`false`(bool)만 올 수 있어요. `if n != 0`처럼 비교식으로 써 주세요."),
    (re.compile(r"`if` and `else` have incompatible types", re.I),
     "`if`와 `else` 갈래가 돌려주는 값의 타입이 같아야 해요. 둘 다 문자열이거나 둘 다 숫자가 되도록 맞춰 주세요."),
    (re.compile(r"doesn't implement `std::fmt::Display`|cannot be formatted with the default formatter", re.I),
     "이 타입은 `{}`로 바로 출력할 수 없어요. 배열·`Vec`·튜플·구조체를 출력하려면 `{:?}`를 쓰고 구조체 위에는 `#[derive(Debug)]`를 붙이세요."),
    (re.compile(r"\bE0384\b|cannot assign twice to immutable variable", re.I),
     "불변 변수(`let`)의 값을 바꾸려 했어요. 값을 수정하려면 `let mut 변수명 = ...`으로 선언하세요."),
    (re.compile(r"\bE0596\b|not declared as mutable", re.I),
     "변수가 가변(`mut`)으로 선언되지 않았어요. 선언할 때 `let mut 변수명 = ...`처럼 `mut`를 붙여 주세요."),
    (re.compile(r"\bE0382\b|borrow of moved value|value used here after move", re.I),
     "소유권(Move)이 다른 곳으로 넘어간 뒤 다시 사용했어요. `&변수`로 빌리거나 `.clone()`을 사용해 보세요."),
    (re.compile(r"\bE0505\b|cannot move out of .* because it is borrowed", re.I),
     "참조로 빌려 쓰는 동안 소유권을 옮기려 했어요. 참조 사용이 끝난 뒤에 이동하거나 `.clone()`을 사용해 보세요."),
    (re.compile(r"\bE0502\b|\bE0499\b|cannot borrow .* as mutable (?:more than once|because it is also borrowed)", re.I),
     "가변 빌림(`&mut`)과 다른 빌림이 겹쳤어요. 같은 스코프에서 `&mut` 참조는 한 번에 하나만 유지하세요."),
    (re.compile(r"\bE0507\b|cannot move out of .* behind a .* reference", re.I),
     "빌린 참조(`&T`)에서 소유권을 통째로 빼내려 했어요. `.clone()`으로 복사하거나 참조 형태 그대로 사용해 보세요."),
    (re.compile(r"\bE0601\b|`main` function not found", re.I),
     "실행 시작점인 `fn main() { ... }` 함수가 빠져 있어요. 파일 안에 `fn main()`을 작성해 주세요."),
    (re.compile(r"\bE0282\b|type annotations needed", re.I),
     "컴파일러가 타입을 자동으로 추론하지 못했어요. `.collect::<Vec<_>>()`나 `let x: i32 = ...`처럼 타입을 명시해 주세요."),
    (re.compile(r"\bE0425\b|cannot find value", re.I),
     "선언되지 않은 변수나 함수 이름이에요. 철자와 대소문자, 변수가 속한 `{ ... }` 범위를 확인해 보세요."),
    (re.compile(r"\bE0433\b|\bE0412\b|cannot find type|use of undeclared crate or module", re.I),
     "타입이나 모듈 이름을 찾지 못했어요. `HashMap`·`VecDeque`·`BTreeMap` 등을 쓴다면 파일 맨 위에 `use std::collections::...;`를 추가하세요."),
    (re.compile(r"\bE0599\b|no method named", re.I),
     "이 타입에서 해당 메서드를 찾지 못했어요. 메서드 철자나 `&str`/`String`/`Vec` 타입 차이를 확인해 보세요."),
    (re.compile(r"\bE0061\b|this function takes \d+ argument", re.I),
     "함수에 전달한 인자 개수가 함수 정의와 달라요. 매개변수 개수와 타입을 다시 맞춰 주세요."),
    (re.compile(r"\bE0308\b|mismatched types", re.I),
     "기대한 타입과 실제 값의 타입이 달라요. 정수/실수(`as f64`)나 `&str`/`String`, 반환 세미콜론(`;`) 유무를 확인하세요."),
    (re.compile(r"\bE0277\b.*cannot be formatted with the default formatter", re.I),
     "이 타입은 `{}`로 바로 출력할 수 없어요. 배열·`Vec`·튜플·구조체를 출력하려면 `{:?}`를 쓰고 구조체 위에는 `#[derive(Debug)]`를 붙이세요."),
    (re.compile(r"\bE0277\b", re.I),
     "필요한 트레이트(능력, 예: `Display`, `PartialOrd`, `Copy`, `Debug`)가 구현되지 않았어요."),
    (re.compile(r"\bE0369\b|cannot (?:add|subtract|multiply|divide|compare)", re.I),
     "두 값의 타입이 연산을 지원하지 않아요. `i32`/`usize`/`f64` 타입이 서로 다르면 `as`로 맞춰 주세요."),
    (re.compile(r"\bE0106\b|missing lifetime specifier", re.I),
     "참조(`&`)를 반환하거나 구조체에 담을 때 수명(`'a`) 표기가 필요해요. 헷갈리면 소유권 타입(`String` 등)을 반환해 보세요."),
    (re.compile(r"comparison operators cannot be chained", re.I),
     "러스트에서는 `0 <= x < 10`처럼 비교를 이어 쓸 수 없어요. `0 <= x && x < 10`처럼 `&&`로 연결해 주세요."),
    (re.compile(r"expected `;`", re.I),
     "문장 끝에 세미콜론(`;`)이 빠졌는지 확인해 보세요."),
    (re.compile(r"expected `!`", re.I),
     "`println!`이나 `vec!` 같은 Rust 매크로 이름 뒤에는 느낌표(`!`)가 꼭 붙어요."),
    (re.compile(r"unclosed delimiter|unexpected closing delimiter|expected `\}|unterminated double quote", re.I),
     "중괄호 `{ }`·소괄호 `( )`·큰따옴표 `\"`의 열고 닫는 짝이 맞는지 확인해 보세요."),
    (re.compile(r"linker .* not found|link\.exe", re.I),
     "Windows 링커(MSVC Build Tools)를 찾지 못했어요. Visual Studio Installer에서 'C++를 사용한 데스크톱 개발'을 확인해 주세요."),
]

_RUST_PANIC_DIAGNOSTICS = [
    (re.compile(r"Option::unwrap\(\).*None", re.I),
     "빈 값(None)인 `Option`에 `.unwrap()`을 호출해 프로그램이 멈췄어요. `.unwrap_or(기본값)`이나 `match`/`if let`을 사용해 보세요."),
    (re.compile(r"Result::unwrap\(\).*Err", re.I),
     "오류(Err)가 담긴 `Result`에 `.unwrap()`을 호출해 멈췄어요. `.parse()`나 파일 읽기 실패 시 `.unwrap_or()`나 `match`로 처리해 보세요."),
    (re.compile(r"index out of bounds", re.I),
     "배열이나 `Vec` 길이보다 큰 인덱스에 접근해 멈췄어요. 인덱스가 `0`부터 `len() - 1` 사이인지 확인해 주세요."),
    (re.compile(r"attempt to subtract with overflow", re.I),
     "부호 없는 정수(`usize`/`u32`)가 0보다 작아져 언더플로가 발생했어요. 뺄셈 전에 크기를 비교하거나 `checked_sub`·`checked_add_signed`를 쓰세요."),
    (re.compile(r"attempt to divide by zero", re.I),
     "0으로 나눌 수 없어요. 나눗셈 전에 분모가 0인지 먼저 확인해 주세요."),
]


def _probe_rustc(executable: Path):
    try:
        if not executable.is_file():
            return None
        proc = subprocess.run(
            [str(executable), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            return None
        line = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
        m = re.search(r"rustc\s+([^\s]+)", line)
        if not m:
            return None
        version = m.group(1)
        cargo_exe = executable.with_name("cargo.exe" if os.name == "nt" else "cargo")
        return {
            "available": True,
            "mode": "system",
            "path": str(executable.resolve()),
            "cargo": str(cargo_exe.resolve()) if cargo_exe.is_file() else "",
            "version": version,
            "label": f"Rust {version} (rustc 연동)",
            "source": "system",
        }
    except (OSError, ValueError, subprocess.TimeoutExpired, IndexError):
        return None


def _candidate_rustcs(custom_path=""):
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

    env_rustc = os.environ.get("CODESTEP_RUSTC", "")
    if env_rustc:
        add(env_rustc, "env")

    found = shutil.which("rustc")
    if found:
        add(found, "path")

    cargo_home = os.environ.get("CARGO_HOME")
    if cargo_home:
        add(Path(cargo_home) / "bin" / "rustc.exe", "cargo-home")
    add(Path.home() / ".cargo" / "bin" / "rustc.exe", "cargo-bin")

    rustup_dir = Path.home() / ".rustup" / "toolchains"
    if rustup_dir.is_dir():
        try:
            for tc in sorted(rustup_dir.iterdir(), reverse=True):
                add(tc / "bin" / "rustc.exe", "rustup")
        except OSError:
            pass

    for pf_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(pf_var)
        if not base or not Path(base).is_dir():
            continue
        try:
            for item in sorted(Path(base).glob("Rust*"), reverse=True):
                add(item / "bin" / "rustc.exe", "installed")
        except OSError:
            pass

    return candidates


def discover_rust_runtime(custom_path="", refresh=False):
    cache_key = str(custom_path or "").strip()
    if not refresh and cache_key in _RUST_CACHE:
        return dict(_RUST_CACHE[cache_key])

    for candidate, source in _candidate_rustcs(cache_key):
        info = _probe_rustc(candidate)
        if info:
            info["source"] = source
            _RUST_CACHE[cache_key] = info
            return dict(info)

    missing = {
        "available": False,
        "mode": "missing",
        "path": "",
        "cargo": "",
        "version": "",
        "label": "rustc 미설치 (설정에서 연동 가능)",
        "source": "missing",
    }
    _RUST_CACHE[cache_key] = missing
    return dict(missing)


def translate_rust_error(stderr_text: str):
    """Attach a concise Korean explanation and first source line number to rustc errors."""
    text = (stderr_text or "").strip()
    line = None
    m = re.search(r"-->\s*[^:\n]+:(\d+):\d+", text)
    if not m:
        m = re.search(r":(\d+):\d+:", text)
    if m:
        try:
            line = int(m.group(1))
        except ValueError:
            line = None

    tips = []
    for pattern, hint in _RUST_DIAGNOSTICS:
        if pattern.search(text) and hint not in tips:
            tips.append(hint)
            if len(tips) >= 2:
                break

    if not text:
        return "Rust 컴파일 또는 실행 중 오류가 발생했어요.", line
    if tips:
        return text + "\n\n[힌트] " + " ".join(tips), line
    return text, line


def _replace_fn_main(code: str) -> str:
    """Rename top-level `fn main(...)` to `fn __codestep_user_main(...)` outside strings/comments."""
    i = 0
    n = len(code)
    depth = 0
    in_line_comment = False
    block_comment_depth = 0
    in_string = False
    escape = False

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if block_comment_depth > 0:
            if ch == "/" and nxt == "*":
                block_comment_depth += 1
                i += 2
            elif ch == "*" and nxt == "/":
                block_comment_depth -= 1
                i += 2
            else:
                i += 1
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment_depth = 1
            i += 2
            continue
        if ch == "'":
            # A char literal such as '"' or '{' must not be read as a string start or a block.
            # A lifetime ('a) has no closing quote, so it does not match and is skipped as one char.
            char_match = _RUST_CHAR_RE.match(code, i)
            i = char_match.end() if char_match else i + 1
            continue
        if ch in "rb" and (i == 0 or not (code[i - 1].isalnum() or code[i - 1] == "_")):
            raw_match = _RUST_RAW_STRING_RE.match(code, i)
            if raw_match:
                closing = code.find('"' + raw_match.group(1), raw_match.end())
                i = n if closing < 0 else closing + 1 + len(raw_match.group(1))
                continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0 and code.startswith("fn", i):
            prev_ok = i == 0 or not (code[i - 1].isalnum() or code[i - 1] == "_")
            after_fn = code[i + 2:]
            m = re.match(r"\s+main\b", after_fn)
            if prev_ok and m:
                start = i + 2 + len(m.group(0)) - 4
                return code[:start] + "__codestep_user_main" + code[start + 4:]
        i += 1

    return code


def _rust_literal(val, mode="auto"):
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return repr(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        if mode == "string":
            return f'String::from("{escaped}")'
        return f'"{escaped}"'
    if isinstance(val, (list, tuple)):
        item_mode = "string" if mode == "vec_string" else "auto"
        inner = ", ".join(_rust_literal(x, mode=item_mode) for x in val)
        if mode in ("vec", "vec_string"):
            return f"vec![{inner}]"
        return f"&[{inner}]"
    return str(val)


def build_rust_check_harness(code: str, function_checks: list) -> str:
    """Create a runnable Rust test harness appended after renaming user `fn main`."""
    base = _replace_fn_main(code)
    lines = [
        base,
        "",
        "#[allow(dead_code)]",
        "fn main() {",
    ]
    for idx, chk in enumerate(function_checks):
        args = chk.get("args", [])
        modes = chk.get("argModes") or ["auto"] * len(args)
        fn_name = chk["name"]
        call_parts = []
        block_lines = []
        for a_idx, (val, mode) in enumerate(zip(args, modes)):
            if mode == "mut_string":
                escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
                var_name = f"__mut_arg_{idx}_{a_idx}"
                block_lines.append(f'    let mut {var_name} = String::from("{escaped}");')
                call_parts.append(f"&mut {var_name}")
            elif mode == "empty_i32_slice":
                call_parts.append("&([] as [i32; 0])")
            elif mode == "raw":
                call_parts.append(str(val))
            else:
                call_parts.append(_rust_literal(val, mode=mode))

        if chk.get("returnsMutArg0"):
            lines.extend(block_lines)
            lines.append(f"    {fn_name}({', '.join(call_parts)});")
            lines.append(f'    println!("__CODESTEP_CHK__:{idx}:{{:?}}", __mut_arg_{idx}_0);')
        else:
            lines.extend(block_lines)
            lines.append(f"    let __res_{idx} = {fn_name}({', '.join(call_parts)});")
            lines.append(f'    println!("__CODESTEP_CHK__:{idx}:{{:?}}", __res_{idx});')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _expected_to_debug_str(expected) -> str:
    if isinstance(expected, bool):
        return "true" if expected else "false"
    if isinstance(expected, str):
        escaped = expected.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(expected, list):
        return "[" + ", ".join(_expected_to_debug_str(item) for item in expected) + "]"
    return repr(expected)


def _format_rust_call(chk):
    parts = []
    for val, mode in zip(chk.get("args", []), chk.get("argModes") or []):
        if mode == "empty_i32_slice":
            parts.append("&[]")
        else:
            parts.append(_rust_literal(val, mode="auto" if mode == "mut_string" else mode))
    if not parts:
        parts = [_rust_literal(val) for val in chk.get("args", [])]
    return f"{chk['name']}({', '.join(parts)})"


MAX_OUTPUT_CHARS = 64_000
_MAX_OUTPUT_BYTES = MAX_OUTPUT_CHARS * 4


class _ExeResult:
    def __init__(self, returncode, stdout, stderr, timed_out=False, overflow=False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.overflow = overflow


def _run_exe(command, input="", timeout=5, cwd=None, creationflags=0):
    """Run a learner program with bounded output.

    An endless `loop { println!(...) }` is the most common beginner mistake. Collecting all of
    its output would use hundreds of MB, so the program is stopped as soon as it prints too
    much, and whatever it printed before a timeout is kept so the learner can see it.
    """
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, creationflags=creationflags)
    captured = {"out": bytearray(), "err": bytearray()}
    overflow = threading.Event()

    def pump(stream, key):
        try:
            while True:
                chunk = stream.read1(16384)
                if not chunk:
                    break
                room = _MAX_OUTPUT_BYTES - len(captured[key])
                captured[key] += chunk[:max(0, room)]
                if len(chunk) > room:
                    overflow.set()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    break
        except (OSError, ValueError):
            pass

    def feed():
        try:
            proc.stdin.write((input or "").encode("utf-8"))
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True),
               threading.Thread(target=feed, daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = not overflow.is_set()
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()
    for thread in threads:
        thread.join(timeout=2)
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass
    out = captured["out"].decode("utf-8", errors="replace").replace("\r\n", "\n")
    err = captured["err"].decode("utf-8", errors="replace").replace("\r\n", "\n")
    too_long = overflow.is_set() or len(out) > MAX_OUTPUT_CHARS
    return _ExeResult(proc.returncode, out[:MAX_OUTPUT_CHARS], err[:MAX_OUTPUT_CHARS], timed_out and not too_long, too_long)


def _run_rustc_compile_and_exec(
    source_code: str,
    rustc_path: str,
    run_cwd: Path,
    stdin: str = "",
    timeout_compile: int = 15,
    timeout_run: int = 5,
    out_tag: str = "main",
):
    with tempfile.TemporaryDirectory(prefix="codestep-rs-") as tmp:
        tmp_dir = Path(tmp)
        rs_file = tmp_dir / f"{out_tag}.rs"
        exe_file = tmp_dir / f"{out_tag}.exe"
        rs_file.write_text(source_code, encoding="utf-8")

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        rustc_dir = str(Path(rustc_path).resolve().parent)
        path_parts = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
        if rustc_dir and rustc_dir.lower() not in [p.lower() for p in path_parts]:
            env["PATH"] = rustc_dir + os.pathsep + env.get("PATH", "")
        try:
            comp = subprocess.run(
                [str(rustc_path), "--edition", "2021", "--color", "never", str(rs_file), "-o", str(exe_file)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_compile,
                cwd=str(tmp_dir),
                env=env,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error": f"Rust 컴파일 시간이 {timeout_compile}초를 넘었어요.", "line": None}
        except OSError:
            return {"ok": False, "output": "", "error": "rustc 컴파일러를 실행하지 못했어요. 설정에서 경로를 확인해 주세요.", "line": None}

        if comp.returncode != 0 or not exe_file.is_file():
            err_msg, line = translate_rust_error(comp.stderr or comp.stdout)
            return {"ok": False, "output": "", "error": err_msg, "line": line}

        try:
            proc = _run_exe([str(exe_file)], input=stdin, timeout=timeout_run, cwd=str(run_cwd), creationflags=flags)
        except OSError as error:
            return {
                "ok": False, "output": "", "line": None,
                "error": f"컴파일된 Rust 실행 파일(.exe)을 시작하지 못했어요 ({error}). 백신 프로그램이 방금 만든 실행 파일을 막았는지 확인해 주세요.",
            }

        if getattr(proc, "overflow", False):
            return {
                "ok": False, "output": proc.stdout or "", "line": None,
                "error": f"출력이 너무 길어 실행을 중단했어요(최대 {MAX_OUTPUT_CHARS:,}자). loop/while 반복이 끝나지 않는지 확인해 주세요.",
            }
        if getattr(proc, "timed_out", False):
            return {
                "ok": False, "output": proc.stdout or "", "line": None,
                "error": f"실행 시간이 {timeout_run}초를 넘었어요. loop/while 종료 조건을 확인해 주세요.",
            }

        if proc.returncode != 0:
            raw_err = (proc.stderr or f"프로그램이 비정상 종료되었어요(종료 코드 {proc.returncode}).").strip()
            panic_tips = [hint for pat, hint in _RUST_PANIC_DIAGNOSTICS if pat.search(raw_err)]
            if panic_tips:
                raw_err = f"{raw_err}\n\n[실행 중 패닉 힌트] {panic_tips[0]}"
            return {"ok": False, "output": proc.stdout or "", "error": raw_err, "line": None}

        return {"ok": True, "output": proc.stdout or "", "error": "", "line": None}


def run_rust_script(script_path: Path, work_dir: Path, stdin="", rust_path=None, function_checks=None, timeout=5):
    """Compile and execute a real .rs workspace file using system rustc."""
    script = Path(script_path).resolve()
    workspace = Path(work_dir).resolve()
    if not isinstance(stdin, str):
        return {"ok": False, "error": "입력값은 문자열이어야 해요.", "output": "", "functionResults": [], "usedSystemRust": False}
    if not script.is_file():
        return {"ok": False, "error": "실습용 Rust 파일(.rs)이 아직 없어요.", "output": "", "functionResults": [], "usedSystemRust": False}
    if not rust_path or not Path(rust_path).is_file():
        return {
            "ok": False,
            "missingCompiler": True,
            "output": "",
            "error": (
                "이 PC에서 Rust 컴파일러(rustc)를 찾지 못했어요.\n"
                "PowerShell에서 `winget install Rustlang.Rustup` 을 실행하거나 https://rustup.rs 에서 Rust를 설치한 뒤,\n"
                "설정 화면에서 '자동 감지로 재검색'을 눌러 주세요."
            ),
            "functionResults": [],
            "usedSystemRust": False,
            "elapsed": 0,
        }

    try:
        raw = script.read_bytes()
    except OSError as error:
        return {"ok": False, "error": f"Rust 소스 파일을 열지 못했어요 ({error}). 다른 프로그램이 파일을 잠그고 있지 않은지 확인해 주세요.",
                "output": "", "functionResults": [], "usedSystemRust": True}
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Older Notepad saves Korean text as ANSI(cp949). The code is recompiled from a UTF-8 copy, so this still works.
        try:
            content = raw.decode("cp949")
        except UnicodeDecodeError:
            return {"ok": False, "error": "Rust 소스 파일의 글자 인코딩을 읽지 못했어요. 편집기에서 '다른 이름으로 저장 → 인코딩: UTF-8'로 저장해 주세요.",
                    "output": "", "functionResults": [], "usedSystemRust": True}

    if len(content) > 32000:
        return {"ok": False, "error": "파일 크기가 너무 커요(최대 32,000자).", "output": "", "functionResults": [], "usedSystemRust": True}
    if not content.strip():
        return {"ok": False, "error": "Rust 코드가 비어 있어요. 코드를 작성한 뒤 저장해 주세요.", "output": "", "functionResults": [], "usedSystemRust": True}

    started = time.perf_counter()
    res = _run_rustc_compile_and_exec(content, rust_path, workspace, stdin=stdin, timeout_run=timeout, out_tag="main")
    func_results = []

    if res["ok"] and function_checks:
        harness = build_rust_check_harness(content, function_checks)
        chk_res = _run_rustc_compile_and_exec(harness, rust_path, workspace, stdin="", timeout_run=timeout, out_tag="check")
        if not chk_res["ok"]:
            err_lines = [ln.strip() for ln in chk_res.get("error", "").splitlines() if ln.strip()]
            hint_line = next((ln for ln in err_lines if ln.startswith("[힌트]")), "")
            first_err = err_lines[0] if err_lines else "함수 시그니처 또는 반환 타입이 다릅니다."
            msg = f"{first_err} {hint_line}".strip()
            for idx, chk in enumerate(function_checks):
                detail = (
                    f"{_format_rust_call(chk)} 검증 컴파일 실패: {msg}"
                    if idx == 0
                    else f"{_format_rust_call(chk)} 검증 컴파일 실패 (함수 이름·매개변수·반환 타입을 확인하세요)"
                )
                func_results.append({
                    "name": chk["name"],
                    "ok": False,
                    "detail": detail,
                })
        else:
            parsed = {}
            for line in chk_res["output"].splitlines():
                if line.startswith("__CODESTEP_CHK__:"):
                    _, idx_s, val_s = line.split(":", 2)
                    parsed[int(idx_s)] = val_s
            for idx, chk in enumerate(function_checks):
                call_txt = _format_rust_call(chk)
                exp_s = chk["expectedDebug"] if "expectedDebug" in chk else _expected_to_debug_str(chk["expected"])
                if idx not in parsed:
                    func_results.append({"name": chk["name"], "ok": False, "detail": f"{call_txt} 결과를 받지 못했어요."})
                else:
                    actual_s = parsed[idx]
                    ok = actual_s == exp_s
                    detail = f"{call_txt} -> {actual_s}" if ok else f"{call_txt} -> {actual_s} (기댓값: {exp_s})"
                    func_results.append({"name": chk["name"], "ok": ok, "detail": detail})

    res["functionResults"] = func_results
    res["usedSystemRust"] = True
    res["elapsed"] = round((time.perf_counter() - started) * 1000)
    return res


def cmd_echo_escape(text):
    """Escape cmd.exe operators so a path can be shown with `echo` exactly as written."""
    return re.sub(r"([\^&|<>()])", r"^\1", str(text))


# `call echo %^ERRORLEVEL%` is evaluated when the line runs. A plain %ERRORLEVEL% is replaced
# when cmd first reads the line, so it would always show 0.
_CONSOLE_FOOTER = " & echo. & call echo [종료 코드 %^ERRORLEVEL% - 창을 닫으려면 아무 키나 누르세요]"


def console_command(inner: str, wait_for_key=True) -> str:
    """Wrap commands for a new cmd.exe window.

    The result must be passed to subprocess as ONE STRING. Passing it as a list makes
    subprocess escape the inner quotes as \\" which cmd.exe does not understand, so
    every quoted program path fails with "is not recognized as a command".
    """
    return f'cmd.exe /d /s /c "{inner}{_CONSOLE_FOOTER}{" & pause>nul" if wait_for_key else ""}"'


def rust_terminal_command(script_path: Path, work_dir: Path, runtime: dict, out_exe: Path, wait_for_key=True) -> str:
    src_name = Path(script_path).name
    inner = (
        f'color 07 & chcp 65001>nul & title Rust {runtime.get("version", "")} - {src_name}'
        f' & echo {cmd_echo_escape(work_dir)}^> rustc --edition 2021 "{src_name}" -o "{Path(out_exe).name}" & echo.'
        f' & "{runtime["path"]}" --edition 2021 "{script_path}" -o "{out_exe}"'
        f' && "{out_exe}"'
    )
    return console_command(inner, wait_for_key)


def launch_rust_terminal(script_path: Path, work_dir: Path, runtime: dict):
    if not runtime.get("available"):
        return False, "터미널 실행에는 rustc 설치가 필요해요. 설정 화면에서 rustc 경로를 확인하거나 설치해 주세요."
    if os.name != "nt":
        return False, "터미널 바로 실행은 Windows에서만 지원해요."
    try:
        out_exe = Path(tempfile.gettempdir()) / f"codestep_{Path(script_path).stem}_{os.getpid()}.exe"
        subprocess.Popen(rust_terminal_command(script_path, work_dir, runtime, out_exe), cwd=str(work_dir),
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return True, "실제 터미널 창에서 Rust 컴파일 및 실행을 시작했어요."
    except OSError as error:
        return False, f"터미널을 열지 못했어요: {error}"
