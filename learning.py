"""Native curriculum, progress, and local-file persistence. No network access."""
from __future__ import annotations

from datetime import date, timedelta, datetime
import json
import os
from pathlib import Path
import shutil

CATALOG = json.loads((Path(__file__).resolve().parent / "data" / "curriculum.json").read_text(encoding="utf-8"))
UNITS = CATALOG["units"]
LESSONS = CATALOG["lessons"]
QUESTIONS = CATALOG["questions"]
SAMPLES = CATALOG["samples"]
LESSON_BY_ID = {lesson["id"]: lesson for lesson in LESSONS}
QUESTION_BY_ID = {question["id"]: question for question in QUESTIONS}
# The JSON stores a separate copy of every lesson inside its unit. Point units at the one lesson
# object so the home path, the lesson screen and the review list can never show different content.
for _unit in UNITS:
    _unit["lessons"] = [LESSON_BY_ID.get(_item["id"], _item) for _item in _unit["lessons"]]
LANGS = [
    ("python", "Python"),
    ("rust", "Rust"),
]
LEVELS = [
    ("all", "전체"),
    ("intro", "입문"),
    ("beginner", "초급"),
    ("intermediate", "중급"),
    ("advanced", "고급"),
    ("exam", "기출 실전"),
]


def fresh_progress():
    return {
        "version": 1, "xp": 0, "completed": {}, "mistakes": {}, "activity": {},
        "reviewCount": 0, "perfectCount": 0,
        "settings": {
            "goal": 20,
            "sound": True,
            "pythonPath": "",
            "rustPath": "",
            "workspaceDir": "",
            "autoVerify": True,
            "unlockAll": False,
            "activeLang": "python",
            "playgroundLang": "python",
        },
    }


def valid_day(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def positive_int(value, maximum=10000000):
    return max(0, min(int(value), maximum)) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf") else 0


def _clean_path_setting(value):
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()[:500]
    return "" if "\x00" in cleaned else cleaned


def normalize_progress(value):
    clean = fresh_progress()
    if not isinstance(value, dict) or value.get("version") != 1:
        return clean
    for key in ("xp", "reviewCount", "perfectCount"):
        clean[key] = positive_int(value.get(key))
    completed = value.get("completed") if isinstance(value.get("completed"), dict) else {}
    for key, record in completed.items():
        if key in LESSON_BY_ID and isinstance(record, dict) and valid_day(record.get("date")):
            clean["completed"][key] = {"date": record["date"], "best": positive_int(record.get("best"), 100), "runs": max(1, positive_int(record.get("runs")))}
    mistakes = value.get("mistakes") if isinstance(value.get("mistakes"), dict) else {}
    for key, record in mistakes.items():
        if key in QUESTION_BY_ID and isinstance(record, dict):
            clean["mistakes"][key] = {"count": max(1, positive_int(record.get("count"))), "date": record.get("date") if valid_day(record.get("date")) else date.today().isoformat()}
    activity = value.get("activity") if isinstance(value.get("activity"), dict) else {}
    for day, record in activity.items():
        if valid_day(day) and isinstance(record, dict):
            clean["activity"][day] = {key: positive_int(record.get(key)) for key in ("xp", "lessons", "reviews")}
    settings = value.get("settings") if isinstance(value.get("settings"), dict) else {}
    clean["settings"] = {
        "goal": settings.get("goal") if settings.get("goal") in (10, 20, 40) else 20,
        "sound": settings.get("sound") is not False,
        "pythonPath": _clean_path_setting(settings.get("pythonPath")),
        "rustPath": _clean_path_setting(settings.get("rustPath")),
        "workspaceDir": _clean_path_setting(settings.get("workspaceDir")),
        "autoVerify": settings.get("autoVerify") is not False,
        "unlockAll": settings.get("unlockAll") is True,
        "activeLang": "rust" if settings.get("activeLang") == "rust" else "python",
        "playgroundLang": "rust" if settings.get("playgroundLang") == "rust" else "python",
    }
    return clean


def compare_written_output(typed, answer):
    """Grade an output the learner wrote by hand: None if it matches, else the first differing line (1-based).

    Spaces at the end of a line and blank lines at the very end cannot be seen on an answer sheet, so
    they are ignored. Everything else (quotes, brackets, spaces between values) must match.
    """
    def clean(text):
        lines = [line.rstrip() for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        return lines
    mine, goal = clean(typed), clean(answer)
    if mine == goal:
        return None
    for number, (written, wanted) in enumerate(zip(mine, goal), 1):
        if written != wanted:
            return number
    return min(len(mine), len(goal)) + 1


def is_unlocked(progress, lesson_id):
    lesson = LESSON_BY_ID.get(lesson_id)
    if not lesson:
        return False
    if progress.get("settings", {}).get("unlockAll") or lesson_id in progress["completed"]:
        return True
    level = lesson.get("level", "intro")
    lang = lesson.get("lang", "python")
    if level == "exam":
        track = [item["id"] for item in LESSONS if item.get("lang", "python") == lang and item.get("unitId") == lesson.get("unitId")]
    else:
        track = [item["id"] for item in LESSONS if item.get("lang", "python") == lang and item.get("level", "intro") == level]
    index = track.index(lesson_id)
    return index == 0 or all(item_id in progress["completed"] for item_id in track[:index])


def next_lesson(progress, lang=None):
    pool = [lesson for lesson in LESSONS if not lang or lang == "all" or lesson.get("lang", "python") == lang] or LESSONS
    return next((lesson for lesson in pool if lesson["id"] not in progress["completed"]), pool[-1])


def activity_today(progress):
    return progress["activity"].get(date.today().isoformat(), {"xp": 0, "lessons": 0, "reviews": 0})


def add_activity(progress, xp, kind, day=None):
    day = day or date.today().isoformat()
    progress["xp"] += xp
    record = progress["activity"].setdefault(day, {"xp": 0, "lessons": 0, "reviews": 0})
    record["xp"] += xp
    record[kind] += 1


def is_midterm_lesson(lesson):
    return isinstance(lesson, dict) and lesson.get("kind") == "midterm"


def finish_lesson(progress, lesson_id, accuracy, day=None):
    if not is_unlocked(progress, lesson_id):
        return 0
    day = day or date.today().isoformat()
    previous = progress["completed"].get(lesson_id)
    midterm = is_midterm_lesson(LESSON_BY_ID.get(lesson_id))
    if previous:
        xp = 10 if midterm else 5
    else:
        xp = (40 if midterm else 20) + ((10 if midterm else 5) if accuracy == 100 else 0)
    progress["completed"][lesson_id] = {"date": previous["date"] if previous else day, "best": max(previous["best"] if previous else 0, positive_int(accuracy, 100)), "runs": (previous["runs"] if previous else 0) + 1}
    if accuracy == 100 and (not previous or previous.get("best", 0) < 100):
        progress["perfectCount"] += 1
    add_activity(progress, xp, "lessons", day)
    return xp


def streak(progress, today=None):
    current = today or date.today()
    if not progress["activity"].get(current.isoformat(), {}).get("xp"):
        current -= timedelta(days=1)
    days = 0
    while progress["activity"].get(current.isoformat(), {}).get("xp"):
        days += 1
        current -= timedelta(days=1)
    return days


def _level_done(progress, level, lang="python"):
    ids = [lesson["id"] for lesson in LESSONS if lesson.get("lang", "python") == lang and lesson.get("level", "intro") == level]
    return bool(ids) and all(lesson_id in progress["completed"] for lesson_id in ids)


def _lang_done(progress, lang):
    ids = [lesson["id"] for lesson in LESSONS if lesson.get("lang", "python") == lang]
    return bool(ids) and all(lesson_id in progress["completed"] for lesson_id in ids)


def _first_sample(lang):
    return next((s for s in SAMPLES if s.get("lang", "python") == lang), SAMPLES[0])


def badges(progress):
    best_streak = max((streak(progress, date.fromisoformat(day)) for day in progress["activity"]), default=0)
    py_ids = [lesson["id"] for lesson in LESSONS if lesson.get("lang", "python") == "python"]
    rust_ids = [lesson["id"] for lesson in LESSONS if lesson.get("lang") == "rust"]
    first_units = [u for u in (next((x for x in UNITS if x.get("lang", "python") == "python"), None),
                               next((x for x in UNITS if x.get("lang") == "rust"), None)) if u]
    first_unit_done = any(
        u["lessons"] and all(item["id"] in progress["completed"] for item in u["lessons"])
        for u in first_units
    )
    return [
        ("첫 번째 발자국", "첫 레슨 완료하기", "🌱", bool(progress["completed"])),
        ("기초가 단단해요", "첫 유닛 완료하기", "⚑", first_unit_done),
        ("성장의 에너지", "100 XP 모으기", "⚡", progress["xp"] >= 100),
        ("꾸준함의 힘", "3일 연속 학습하기", "♨", best_streak >= 3),
        ("실수도 내 편", "오답 5문제 복습하기", "↻", progress["reviewCount"] >= 5),
        ("빈틈없는 한 걸음", "레슨 3회 만점으로 완료", "★", progress["perfectCount"] >= 3),
        ("코드 탐험가", "500 XP 모으기", "◈", progress["xp"] >= 500),
        ("입문 마스터", "Python 입문 · 중간 시험 완료", "🎓", _level_done(progress, "intro", "python")),
        ("초급 정복", "Python 초급 · 중간 시험 완료", "◔", _level_done(progress, "beginner", "python")),
        ("중급 도약", "Python 중급 · 중간 시험 완료", "◑", _level_done(progress, "intermediate", "python")),
        ("고급 알고리즘", "Python 고급 · 중간 시험 완료", "◕", _level_done(progress, "advanced", "python")),
        ("기출 실전 마스터", "Python 기출 실전 완료", "♛", _level_done(progress, "exam", "python")),
        ("파이썬 완전 정복", "Python 전 과정 완료", "♜", _lang_done(progress, "python")),
        ("러스트 첫 걸음", "Rust 첫 레슨 완료하기", "🦀", any(lid in progress["completed"] for lid in rust_ids)),
        ("러스트 입문 마스터", "Rust 입문 · 중간 시험 완료", "🧭", _level_done(progress, "intro", "rust")),
        ("러스트 초급 정복", "Rust 초급 · 중간 시험 완료", "⚙", _level_done(progress, "beginner", "rust")),
        ("러스트 중급 도약", "Rust 중급 · 중간 시험 완료", "⛓", _level_done(progress, "intermediate", "rust")),
        ("러스트 고급 마스터", "Rust 고급 · 중간 시험 완료", "❖", _level_done(progress, "advanced", "rust")),
        ("러스트 실기 마스터", "Rust 기출·실기 단계 완료", "🏅", _level_done(progress, "exam", "rust")),
        ("러스트 완전 정복", "Rust 전 과정 완료", "🛡", _lang_done(progress, "rust")),
        ("듀얼 트랙 입문", "Python · Rust 각 1레슨 완료", "⇄", any(lid in progress["completed"] for lid in py_ids) and any(lid in progress["completed"] for lid in rust_ids)),
        ("코드스텝 마스터", f"{len(LESSONS)}개 전체 레슨 완료", "🏆", len(progress["completed"]) == len(LESSONS)),
    ]


class ProgressStore:
    def __init__(self, folder=None, legacy_folder=None):
        local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        self.folder = Path(folder) if folder else local_app / "CodeStep"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "progress.json"
        if not self.path.exists():
            old_dir = Path(legacy_folder) if legacy_folder else (None if folder else local_app / "PyStep")
            if old_dir and (old_dir / "progress.json").is_file():
                try:
                    shutil.copy2(old_dir / "progress.json", self.path)
                    if not (self.folder / "draft.json").exists() and (old_dir / "draft.json").is_file():
                        shutil.copy2(old_dir / "draft.json", self.folder / "draft.json")
                except OSError:
                    pass
        self.warning = ""
        self.progress = fresh_progress()
        if self.path.exists():
            try:
                self.progress = normalize_progress(json.loads(self.path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                self.warning = "기존 기록을 읽지 못했어요. 원본을 별도로 보관하고 새 기록으로 시작해요."
                try:
                    backup = self.folder / ("progress-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
                    backup.write_bytes(self.path.read_bytes())
                except OSError:
                    self.warning = "기록을 읽거나 보관하지 못했어요. 저장 폴더의 권한을 확인해 주세요."
        py_sample = _first_sample("python")
        rs_sample = _first_sample("rust")
        self.draft = {
            "code": py_sample["code"],
            "stdin": py_sample.get("stdin", ""),
            "sample": py_sample["id"],
            "rustCode": rs_sample["code"],
            "rustStdin": rs_sample.get("stdin", ""),
            "rustSample": rs_sample["id"],
        }
        try:
            draft = json.loads((self.folder / "draft.json").read_text(encoding="utf-8"))
            if isinstance(draft, dict) and isinstance(draft.get("code"), str):
                self.draft.update({
                    "code": draft["code"][:32000],
                    "stdin": str(draft.get("stdin", ""))[:4000],
                    "sample": str(draft.get("sample", py_sample["id"])),
                })
                if isinstance(draft.get("rustCode"), str):
                    self.draft["rustCode"] = draft["rustCode"][:32000]
                if isinstance(draft.get("rustStdin"), str):
                    self.draft["rustStdin"] = draft["rustStdin"][:4000]
                if isinstance(draft.get("rustSample"), str):
                    self.draft["rustSample"] = draft["rustSample"]
        except (ValueError, OSError):
            pass

    @staticmethod
    def write_json(path, value):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def save(self):
        self.write_json(self.path, self.progress)

    def save_draft(self):
        self.write_json(self.folder / "draft.json", self.draft)

    def export(self, path):
        Path(path).write_text(json.dumps(self.progress, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_import(self, path):
        path = Path(path)
        if path.stat().st_size > 1000000:
            raise ValueError("1 MB 이하의 기록 파일을 선택해 주세요.")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("completed"), dict) or not isinstance(value.get("activity"), dict):
            raise ValueError("올바른 코드스텝 학습 기록 파일을 선택해 주세요.")
        return normalize_progress(value)

    def reset(self):
        backup = self.folder / ("progress-before-reset-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
        self.export(backup)
        self.progress = fresh_progress()
        self.save()
        return backup
