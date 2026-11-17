"""Run every "자주 하는 실수" (pitfall) in data/curriculum.json and store what a learner really sees.

Each pitfall has wrong code that must fail the declared way and fixed code that must run:
  expect = "NameError", "SyntaxError", ...   Python error name
  expect = "E0384", "expected `;`", ...       text that must appear in the rustc error
  expect = "output"                          no error, but a wrong result (stored as wrongOutput)
The message shown in the app comes from the app's own runner, never typed by hand, so the lesson
always matches what happens when the learner makes that mistake.

usage (from the project folder):
  .build-python\\python.exe tools\\refresh_pitfalls.py           re-run all and write data/curriculum.json
  .build-python\\python.exe tools\\refresh_pitfalls.py --check   verify only; exit code 1 on any problem
"""
from __future__ import annotations

import builtins
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "curriculum.json"
sys.path.insert(0, str(ROOT))

from code_executor import run_workspace_script  # noqa: E402
from rust_bridge import discover_rust_runtime, run_rust_script  # noqa: E402

GENERATED = ("message", "wrongOutput", "fixOutput")


def _run(lang, code, stdin, rustc):
    with tempfile.TemporaryDirectory(prefix="codestep-pitfall-") as tmp:
        folder = Path(tmp)
        script = folder / ("main.rs" if lang == "rust" else "main.py")
        script.write_text(code, encoding="utf-8")
        if lang == "rust":
            return run_rust_script(script, folder, stdin=stdin, rust_path=rustc)
        return run_workspace_script(script, folder, stdin=stdin, python_path=sys.executable)


def _first_lines(lang, error):
    lines = [line.strip() for line in (error or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if lang == "rust":
        hint = next((line for line in lines if line.startswith("[힌트]")), "")
        return lines[0] + ("\n" + hint if hint else "")
    return lines[0]


def evaluate(lang, pitfall, rustc):
    """Return (generated fields, problems) for one pitfall."""
    problems = []
    expect = pitfall.get("expect", "")
    stdin = pitfall.get("stdin", "")
    generated = {}
    wrong = _run(lang, pitfall["wrong"], stdin, rustc)
    if expect == "output":
        if not wrong.get("ok"):
            problems.append(f"wrong code should run without an error but failed: {wrong.get('error', '')[:160]}")
        generated["wrongOutput"] = (wrong.get("output") or "").rstrip("\n")
    else:
        if wrong.get("ok"):
            problems.append(f"wrong code ran without an error, expected {expect}")
        elif lang == "python" and isinstance(getattr(builtins, expect, None), type) and issubclass(getattr(builtins, expect), SyntaxError):
            try:
                compile(pitfall["wrong"], "main.py", "exec")
                problems.append(f"wrong code compiles, expected {expect}")
            except SyntaxError as error:
                if not isinstance(error, getattr(builtins, expect)):
                    problems.append(f"expected {expect}, got {type(error).__name__}")
        elif expect not in (wrong.get("error") or ""):
            problems.append(f"expected '{expect}' in the error, got: {(wrong.get('error') or '')[:160]}")
        generated["message"] = _first_lines(lang, wrong.get("error"))
    fixed = _run(lang, pitfall["fix"], stdin, rustc)
    if not fixed.get("ok"):
        problems.append(f"fixed code fails: {(fixed.get('error') or '')[:160]}")
    generated["fixOutput"] = (fixed.get("output") or "").rstrip("\n")
    if expect == "output" and generated["fixOutput"] == generated.get("wrongOutput"):
        problems.append("fixed code prints the same as the wrong code")
    return generated, problems


def run(check_only=False):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    rust = discover_rust_runtime()
    versions = {"python": sys.version.split()[0], "rustc": rust.get("version", "")}
    recorded = catalog.get("pitfallsGeneratedWith", {})
    problems, stale, count = [], [], 0
    results = {}
    for lesson in catalog["lessons"]:
        lang = lesson.get("lang", "python")
        for index, pitfall in enumerate(lesson.get("pitfalls") or []):
            ident = f"{lesson['id']}#{index + 1} {pitfall.get('title', '')}"
            for field in ("title", "wrong", "fix", "why", "expect"):
                if not str(pitfall.get(field, "")).strip():
                    problems.append(f"{ident}: missing '{field}'")
            if lang == "rust" and not rust.get("available"):
                continue
            count += 1
            generated, found = evaluate(lang, pitfall, rust.get("path"))
            problems.extend(f"{ident}: {item}" for item in found)
            results[(lesson["id"], index)] = generated
            same_tools = recorded.get("rustc" if lang == "rust" else "python") == versions["rustc" if lang == "rust" else "python"]
            if same_tools and any(pitfall.get(key) != generated.get(key) for key in GENERATED if key in generated):
                stale.append(ident)
    if check_only:
        for item in problems:
            print("PROBLEM:", item)
        for item in stale:
            print("STALE (run tools/refresh_pitfalls.py):", item)
        print(f"checked {count} pitfalls with Python {versions['python']}, rustc {versions['rustc'] or 'not installed'}")
        return 1 if problems or stale else 0
    if problems:
        for item in problems:
            print("PROBLEM:", item)
        print("Nothing written. Fix the pitfalls above first.")
        return 1
    for lesson_list in ([catalog["lessons"]] + [unit["lessons"] for unit in catalog["units"]]):
        for lesson in lesson_list:
            for index, pitfall in enumerate(lesson.get("pitfalls") or []):
                generated = results.get((lesson["id"], index))
                if generated:
                    for key in GENERATED:
                        pitfall.pop(key, None)
                    pitfall.update(generated)
    catalog["pitfallsGeneratedWith"] = versions
    with CATALOG.open("w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(f"updated {count} pitfalls (Python {versions['python']}, rustc {versions['rustc'] or 'not installed'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(check_only="--check" in sys.argv))
