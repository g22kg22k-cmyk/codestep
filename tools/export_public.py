"""Make a clean copy of the project for a public repository (GitHub).

Only allowed files are copied: source, learning data, icons, tests, tools, build scripts, and the
ready-to-run program (dist/CodeStep.exe, placed in the copy as CodeStep.exe so the folder works on a
PC without Python). Never copied: build folders, test results, the downloaded build Python, caches
and the old web version. Everything is checked for personal details before anything is written:
  - this PC's user name, home folder and the project's own absolute path (also inside the EXE,
    whose compressed contents are unpacked entry by entry)
  - in text files, any absolute Windows user path and any e-mail address
The values are taken from the environment at run time, so no personal value is written here.
An EXE older than the source it is built from is refused: rebuild it with build-exe.ps1 first.

usage (from the project folder):
  .build-python\\python.exe tools\\export_public.py <target folder>
  .build-python\\python.exe tools\\export_public.py <target folder> --replace   # update a previous export
  add --no-exe to leave the program out (source only)
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".codestep-public-copy"
ALLOWED_FILES = [
    "desktop.py", "native_app.py", "learning.py", "code_executor.py", "runner.py", "python_bridge.py",
    "rust_bridge.py", "native_selftest.py", "CodeStep.spec", "build-exe.ps1", "setup-build-python.ps1",
    "start.bat", "start.ps1", "requirements-build.txt", "README.md", "LICENSE", "THIRD_PARTY_LICENSES.txt",
    ".gitignore", ".gitattributes",
]
ALLOWED_GLOBS = [
    "data/curriculum.json",
    "assets/*.png", "assets/*.ico", "assets/version_info.txt",
    "tests/test_*.py", "tests/check_exe.py",
    "tools/*.py",
]
EXE_SOURCE = "dist/CodeStep.exe"
EXE_TARGET = "CodeStep.exe"
# Everything PyInstaller puts into the EXE; the EXE must be newer than all of these.
EXE_INPUTS = ["desktop.py", "native_app.py", "learning.py", "code_executor.py", "runner.py", "python_bridge.py",
              "rust_bridge.py", "native_selftest.py", "CodeStep.spec", "THIRD_PARTY_LICENSES.txt",
              "data/curriculum.json", "assets/*"]
TEXT_SUFFIXES = {".py", ".ps1", ".bat", ".spec", ".txt", ".md", ".json", ".gitignore", ".gitattributes", ""}


def personal_patterns():
    """Literal strings that must never appear, built from this PC (case-insensitive)."""
    values = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), str(Path.home()), str(ROOT),
              os.environ.get("USERPROFILE", ""), os.environ.get("COMPUTERNAME", "")}
    expanded = set()
    for value in values:
        value = value.strip()
        if len(value) >= 3:
            expanded.update({value, value.replace("\\", "/"), value.replace("\\", "\\\\")})
    return sorted(expanded, key=len, reverse=True)


GENERIC = [
    re.compile(rb"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}(?!<|%|\{|\.\.\.)[^\\/\s\"'<>]+", re.I),  # a user folder path
    re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),                         # e-mail address
]
EMAIL = GENERIC[1]
# Domains reserved for examples (RFC 2606 / RFC 6761): an address there can never belong to a person.
# Lessons use them to teach e-mail parsing.
RESERVED_EXAMPLE_DOMAIN = re.compile(rb"@(?:[a-z0-9-]+\.)*(?:example\.(?:com|net|org)|example|test|invalid)$", re.I)
# License notices must be copied word for word and include their authors' contact addresses.
# The personal-value check (this PC's user name, home and project path) still applies to them.
VERBATIM_NOTICES = {"THIRD_PARTY_LICENSES.txt"}


def exe_problem():
    """Why dist/CodeStep.exe cannot be published as it is, or None."""
    exe = ROOT / EXE_SOURCE
    if not exe.is_file():
        return f"{EXE_SOURCE} does not exist. Build it with build-exe.ps1 (or use --no-exe for a source-only copy)."
    inputs = [p for pattern in EXE_INPUTS for p in ROOT.glob(pattern) if p.is_file()]
    newest = max(inputs, key=lambda p: p.stat().st_mtime)
    if exe.stat().st_mtime < newest.stat().st_mtime:
        return (f"{EXE_SOURCE} is older than {newest.relative_to(ROOT)}, so it would not match the source. "
                "Rebuild it with build-exe.ps1 and export again.")
    return None


def collect(include_exe=True):
    """(source, path inside the copy) for every file that will be published."""
    files = []
    for name in ALLOWED_FILES:
        path = ROOT / name
        if not path.is_file():
            raise SystemExit(f"Missing project file: {name}. Nothing was exported.")
        files.append((path, Path(name)))
    for pattern in ALLOWED_GLOBS:
        matches = sorted(p for p in ROOT.glob(pattern) if p.is_file())
        if not matches:
            raise SystemExit(f"Nothing matches {pattern}. Nothing was exported.")
        files.extend((p, p.relative_to(ROOT)) for p in matches)
    if include_exe:
        problem = exe_problem()
        if problem:
            raise SystemExit(problem + " Nothing was exported.")
        files.append((ROOT / EXE_SOURCE, Path(EXE_TARGET)))
    return files


def _literal_findings(name, data, literals):
    low = data.lower()
    found = []
    for text in literals:
        for encoded in (text.lower().encode("utf-8"), text.lower().encode("utf-16-le")):
            if encoded in low:
                found.append(f"personal value '{text}' in {name}")
                break
    return found


def scan_exe(path: Path, literals):
    """Check the EXE and every compressed entry inside it for this PC's personal values.

    Generic patterns are not used here: Python's own files contain example user-folder paths (in the
    ntpath documentation) and maintainer addresses, which are not personal to this PC.
    """
    findings = _literal_findings("the EXE file", path.read_bytes(), literals)
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        return findings + ["cannot look inside the EXE: PyInstaller is missing; run this tool with .build-python\\python.exe"]
    try:
        archive = CArchiveReader(str(path))
        for name in archive.toc:
            data = archive.extract(name)
            if not data:
                continue
            findings += _literal_findings(name, data, literals)
            if data[:4] == b"PYZ\x00":
                embedded = archive.open_embedded_archive(name)
                for module in embedded.toc:
                    findings += _literal_findings(f"{name}/{module}", embedded.extract(module, raw=True) or b"", literals)
    except Exception as error:  # noqa: BLE001 - anything unreadable must block the export
        findings.append(f"cannot look inside the EXE ({type(error).__name__}: {error})")
    return findings


def scan(path: Path, literals):
    """Return a list of findings for one file (literal personal values and generic patterns)."""
    if path.suffix.lower() == ".exe":
        return scan_exe(path, literals)
    raw = path.read_bytes()
    findings = []
    haystacks = [raw.lower()]
    if path.suffix.lower() not in TEXT_SUFFIXES:
        try:
            haystacks.append(raw.decode("utf-16-le", errors="ignore").encode("utf-8").lower())
        except UnicodeError:
            pass
    for text in literals:
        encoded = text.lower().encode("utf-8")
        if any(encoded in hay for hay in haystacks):
            findings.append(f"personal value '{text}'")
    for hay in haystacks:
        for regex in GENERIC:
            if regex is EMAIL and path.name in VERBATIM_NOTICES:
                continue
            for match in regex.finditer(hay):
                if regex is EMAIL and RESERVED_EXAMPLE_DOMAIN.search(match.group(0)):
                    continue
                findings.append(f"looks personal: {match.group(0)[:60]!r}")
    return findings


def _digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(target: Path, replace=False, include_exe=True):
    target = target.resolve()
    if target == ROOT or ROOT in target.parents:
        raise SystemExit("The target must be outside the project folder.")
    if target.exists() and any(target.iterdir()):
        if not replace:
            raise SystemExit(f"{target} is not empty. Use --replace to update a previous export.")
        if not (target / MARKER).is_file():
            raise SystemExit(f"{target} was not made by this tool ({MARKER} is missing); not touching it.")
    # Check everything first; the existing copy is only touched once the check has passed.
    files = collect(include_exe)
    literals = personal_patterns()
    problems = []
    for source, inside in files:
        problems.extend(f"{inside}: {item}" for item in scan(source, literals))
    if problems:
        for item in problems:
            print("BLOCKED:", item)
        raise SystemExit("Personal details found; nothing was exported or changed. Remove them and run again.")
    if target.exists():
        for child in target.iterdir():
            if child.name == ".git":  # an existing repository history stays as it is
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    target.mkdir(parents=True, exist_ok=True)
    checked = {}
    for source, inside in files:
        destination = target / inside
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        checked[destination] = source
    (target / MARKER).write_text("Made by tools/export_public.py; safe to replace with --replace.\n", encoding="ascii")
    # Second pass on what actually landed in the target. The EXE was already unpacked and checked;
    # here it only has to be byte-for-byte the file that was checked.
    after = [p for p in target.rglob("*") if p.is_file() and ".git" not in p.relative_to(target).parts]
    leftovers = []
    for path in after:
        if path.suffix.lower() == ".exe":
            source = checked.get(path)
            if source is None or _digest(path) != _digest(source):
                leftovers.append(f"{path.relative_to(target)}: not the checked EXE")
            continue
        leftovers.extend(f"{path.relative_to(target)}: {item}" for item in scan(path, literals))
    if leftovers:
        for item in leftovers:
            print("BLOCKED:", item)
        raise SystemExit("Personal details found in the export; delete the target folder before sharing it.")
    size = sum(p.stat().st_size for p in after)
    program = " including CodeStep.exe" if include_exe else " (source only)"
    print(f"Exported {len(after)} files ({size / 1024 / 1024:.1f} MB){program} to {target.name}; no personal details found.")
    return 0


if __name__ == "__main__":
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(arguments) != 1:
        raise SystemExit(__doc__)
    raise SystemExit(export(Path(arguments[0]), replace="--replace" in sys.argv, include_exe="--no-exe" not in sys.argv))
