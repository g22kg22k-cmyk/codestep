r"""Full curriculum audit: every answer, solution, starter, example and sample is actually executed.

Checks that each coding answer passes and each untouched starter does not, that every example
prints what the lesson says it prints, and that playground samples run. Takes about 2 minutes.

usage (from the project folder):
  .build-python\python.exe tools\audit_curriculum.py . test-results\audit.json [all|structure|fill|code|code-python|code-rust|examples|examples-python|examples-rust|samples]
  set CODESTEP_AUDIT_PYTHON=<python.exe> to check learner code on another installed Python.
"""
import ast
import collections
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
ONLY = sys.argv[3] if len(sys.argv) > 3 else "all"
sys.path.insert(0, str(PROJECT))

from learning import LESSONS, QUESTIONS, SAMPLES, UNITS  # noqa: E402
from python_bridge import (WorkspaceManager, discover_python_runtime, discover_rust_runtime,  # noqa: E402
                           verify_workspace_question)
from code_executor import run_workspace_script  # noqa: E402
from rust_bridge import run_rust_script  # noqa: E402

import os
py_rt = discover_python_runtime(os.environ.get("CODESTEP_AUDIT_PYTHON", ""), refresh=True)
rs_rt = discover_rust_runtime()
print("python runtime:", py_rt["label"], "| rust runtime:", rs_rt["label"], flush=True)

issues = []


def issue(kind, ident, detail):
    issues.append({"kind": kind, "id": ident, "detail": detail})
    print(f"  !! [{kind}] {ident}: {detail[:300]}", flush=True)


def norm(text):
    return (text or "").replace("\r\n", "\n").rstrip("\n")


def run_code(lang, code, stdin="", fixtures=None):
    with tempfile.TemporaryDirectory(prefix="audit-") as tmp:
        folder = Path(tmp)
        for name, content in (fixtures or {}).items():
            (folder / name).write_text(content, encoding="utf-8")
        script = folder / ("main.rs" if lang == "rust" else "main.py")
        script.write_text(code, encoding="utf-8")
        if lang == "rust":
            return run_rust_script(script, folder, stdin=stdin, rust_path=rs_rt.get("path"))
        return run_workspace_script(script, folder, stdin=stdin, python_path=py_rt.get("path") or None)


def verify(question, code):
    lang = question.get("lang", "python")
    with tempfile.TemporaryDirectory(prefix="audit-") as tmp:
        folder = Path(tmp)
        name = "main.rs" if lang == "rust" else "main.py"
        _, script, _ = WorkspaceManager(folder, isolated=True).prepare_workspace(
            folder / "task", name, code, fixtures=question.get("fixtures"))
        return verify_workspace_question(folder / "task", script, question, rs_rt if lang == "rust" else py_rt)


started = time.time()

# ---------- structure ----------
if ONLY in ("all", "structure"):
    print("== structure ==", flush=True)
    ids = collections.Counter(q["id"] for q in QUESTIONS)
    for key, count in ids.items():
        if count > 1:
            issue("dup-question-id", key, f"{count} times")
    for lesson in LESSONS:
        if not lesson.get("questions"):
            issue("lesson-empty", lesson["id"], "no questions")
        for field in ("title", "subtitle", "body"):
            if not str(lesson.get(field, "")).strip():
                issue("lesson-missing-field", lesson["id"], field)
        if not lesson.get("steps"):
            issue("lesson-no-steps", lesson["id"], "")
        if not lesson.get("examples"):
            issue("lesson-no-examples", lesson["id"], "")
    for q in QUESTIONS:
        qid = q["id"]
        for field in ("prompt", "explanation", "hint"):
            if not str(q.get(field, "")).strip():
                issue("question-missing-field", qid, field)
        if q["type"] in ("choice", "fill"):
            opts = q.get("options") or []
            if q.get("answer") not in opts:
                issue("answer-not-in-options", qid, f"{q.get('answer')!r} / {opts!r}")
            if len(set(opts)) != len(opts):
                issue("duplicate-options", qid, repr(opts))
            if len(opts) < 2:
                issue("too-few-options", qid, repr(opts))
            if len(opts) > 4:
                issue("more-than-4-options", qid, f"{len(opts)} options (number keys cover 1-4 only)")
            # Several blanks are fine: the app fills every ___ with the chosen option.
            if q["type"] == "fill" and "___" not in q.get("code", ""):
                issue("fill-no-blank", qid, repr(q.get("code")))
        elif q["type"] == "order":
            if sorted(q.get("tokens", [])) != sorted(q.get("answer", [])):
                issue("order-token-mismatch", qid, f"tokens={q.get('tokens')!r} answer={q.get('answer')!r}")
            if q.get("tokens") == q.get("answer") and len(q.get("tokens", [])) < 2:
                issue("order-trivial", qid, "")
        elif q["type"] == "output":
            if not str(q.get("code", "")).strip() or not str(q.get("answer", "")).strip():
                issue("output-missing-field", qid, "code and answer are both required")
        elif q["type"] == "code":
            for field in ("starter", "solution"):
                if not str(q.get(field, "")).strip():
                    issue("code-missing-field", qid, field)
            if not (q.get("expected") or q.get("functionChecks") or q.get("fileChecks")):
                issue("code-no-check", qid, "no expected/functionChecks/fileChecks: anything passes")

# ---------- python fill / order syntax + ambiguity ----------
if ONLY in ("all", "fill"):
    print("== python fill/order ==", flush=True)
    for q in QUESTIONS:
        if q.get("lang", "python") != "python":
            continue
        qid = q["id"]
        if q["type"] == "fill" and "___" in q.get("code", ""):
            good = q["code"].replace("___", str(q["answer"]))
            try:
                ast.parse(good)
            except SyntaxError as error:
                # A snippet that only shows the header of a block (if ...:) is a deliberate fragment.
                if not (isinstance(error, IndentationError) and error.lineno == len(good.splitlines()) + 1
                        or "expected an indented block" in error.msg):
                    issue("fill-answer-syntax", qid, f"{error.msg}: {good!r}")
                continue
            base = run_code("python", good, stdin=q.get("stdin", ""))
            if not base.get("ok"):
                # Most blanks show one line taken from a larger program (it uses names defined
                # elsewhere), so a runtime error here is expected; only complete snippets are compared.
                continue
            if not base.get("output", "").strip():
                continue
            for option in q["options"]:
                if option == q["answer"]:
                    continue
                alt = q["code"].replace("___", str(option))
                try:
                    ast.parse(alt)
                except SyntaxError:
                    continue
                other = run_code("python", alt, stdin=q.get("stdin", ""))
                if other.get("ok") and norm(other.get("output")) == norm(base.get("output")):
                    issue("fill-ambiguous", qid, f"option {option!r} gives the same output as answer {q['answer']!r} :: {q['code']!r}")
        elif q["type"] == "order":
            joined = q.get("separator", "").join(q["answer"])
            try:
                ast.parse(joined)
            except SyntaxError as error:
                issue("order-answer-syntax", qid, f"{error.msg}: {joined!r}")

# ---------- code questions ----------
if ONLY in ("all", "code", "code-python", "code-rust"):
    print("== code questions: solution must pass, starter must not ==", flush=True)
    code_qs = [q for q in QUESTIONS if q["type"] == "code"]
    for n, q in enumerate(code_qs, 1):
        lang = q.get("lang", "python")
        if ONLY == "code-python" and lang != "python":
            continue
        if ONLY == "code-rust" and lang != "rust":
            continue
        qid = q["id"]
        res = verify(q, q["solution"])
        if not res.get("passed"):
            failed = [c for c in res.get("checks", []) if not c["ok"]]
            issue("solution-fails", qid, json.dumps(failed, ensure_ascii=False))
        res2 = verify(q, q["starter"])
        if res2.get("passed"):
            issue("starter-already-passes", qid, "the untouched starter code is graded as correct")
        if n % 10 == 0:
            print(f"  code {n}/{len(code_qs)}  ({time.time() - started:.0f}s)", flush=True)

# ---------- written-output questions ----------
if ONLY in ("all", "code", "code-python"):
    print("== written-output questions: the answer must be what the program really prints ==", flush=True)
    for q in QUESTIONS:
        if q["type"] != "output":
            continue
        res = run_code(q.get("lang", "python"), q["code"])
        if not res.get("ok"):
            issue("output-question-error", q["id"], f"{res.get('error')}")
        elif norm(res.get("output")) != norm(q["answer"]):
            issue("output-answer-mismatch", q["id"], f"answer={norm(q['answer'])!r} actual={norm(res.get('output'))!r}")

# ---------- lesson examples ----------
if ONLY in ("all", "examples", "examples-python", "examples-rust"):
    print("== lesson examples: shown output must match real output ==", flush=True)
    total = sum(len(l.get("examples") or []) for l in LESSONS)
    n = 0
    for lesson in LESSONS:
        lang = lesson.get("lang", "python")
        for idx, ex in enumerate(lesson.get("examples") or []):
            n += 1
            if ONLY == "examples-python" and lang != "python":
                continue
            if ONLY == "examples-rust" and lang != "rust":
                continue
            ident = f"{lesson['id']}#ex{idx + 1}"
            res = run_code(lang, ex.get("code", ""), stdin=ex.get("stdin", ""))
            if not res.get("ok"):
                issue("example-error", ident, f"{res.get('error')}")
            elif ex.get("output") and norm(res.get("output")) != norm(ex["output"]):
                issue("example-output-mismatch", ident, f"shown={norm(ex['output'])!r} actual={norm(res.get('output'))!r}")
            if n % 25 == 0:
                print(f"  examples {n}/{total}  ({time.time() - started:.0f}s)", flush=True)
        if lang == ("rust" if ONLY == "examples-python" else "python" if ONLY == "examples-rust" else None):
            continue
        base = lesson.get("example", "")
        if base.strip() and (ONLY in ("all", "examples") or ONLY.endswith(lang)):
            res = run_code(lang, base)
            if not res.get("ok") and "EOF" not in str(res.get("error")) and "입력값" not in str(res.get("error")):
                issue("lesson-example-error", lesson["id"], f"{res.get('error')}")

# ---------- playground samples ----------
if ONLY in ("all", "samples"):
    print("== playground samples ==", flush=True)
    for s in SAMPLES:
        lang = s.get("lang", "python")
        res = run_code(lang, s["code"], stdin=s.get("stdin", ""))
        if not res.get("ok"):
            issue("sample-error", s["id"], f"{res.get('error')}")
        elif s.get("expected") and norm(res.get("output")) != norm(s["expected"]):
            issue("sample-output-mismatch", s["id"], f"expected={norm(s['expected'])!r} actual={norm(res.get('output'))!r}")

OUT.write_text(json.dumps(issues, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"DONE {ONLY}: {len(issues)} issue(s) in {time.time() - started:.0f}s -> {OUT}", flush=True)
