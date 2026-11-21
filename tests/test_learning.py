import json
from datetime import date
from pathlib import Path
import tempfile
import unittest

from learning import (ProgressStore, fresh_progress, normalize_progress, is_unlocked,
                      finish_lesson, streak, badges, UNITS, LESSONS, QUESTIONS, SAMPLES)
from code_executor import run_workspace_script


class LearningTests(unittest.TestCase):
    def test_unlock_and_repeat_rewards(self):
        progress = fresh_progress()
        self.assertEqual(finish_lesson(progress, "numbers", 100), 0)
        self.assertFalse(is_unlocked(progress, "numbers"))
        self.assertEqual(finish_lesson(progress, "hello", 100), 25)
        self.assertTrue(is_unlocked(progress, "numbers"))
        self.assertEqual(finish_lesson(progress, "hello", 75), 5)
        self.assertEqual(progress["completed"]["hello"]["best"], 100)
        self.assertEqual(progress["completed"]["hello"]["runs"], 2)
        self.assertEqual(progress["perfectCount"], 1)

    def test_streak_across_year_boundary_and_historical_badge(self):
        progress = fresh_progress()
        for day in ("2025-12-30", "2025-12-31", "2026-01-01"):
            progress["activity"][day] = {"xp": 20, "lessons": 1, "reviews": 0}
        self.assertEqual(streak(progress, date(2026, 1, 2)), 3)
        self.assertEqual(streak(progress, date(2026, 1, 3)), 0)
        self.assertTrue(next(unlocked for name, _, _, unlocked in badges(progress) if name == "꾸준함의 힘"))

    def test_import_sanitizes_invalid_dates_ids_and_numbers(self):
        progress = fresh_progress()
        progress.update(xp=float("inf"), reviewCount=-10, perfectCount=True)
        progress["completed"] = {"unknown": {"date": "2026-01-01"}, "hello": {"date": "2026-02-30"}}
        progress["activity"] = {"2026-99-99": {"xp": 10}}
        progress["mistakes"] = {"hello-1": {"count": -1}, "unknown": {"count": 1}}
        clean = normalize_progress(progress)
        self.assertEqual(clean["xp"], 0)
        self.assertEqual(clean["reviewCount"], 0)
        self.assertEqual(clean["perfectCount"], 0)
        self.assertEqual(clean["completed"], {})
        self.assertEqual(clean["activity"], {})
        self.assertEqual(set(clean["mistakes"]), {"hello-1"})
        self.assertEqual(clean["mistakes"]["hello-1"]["count"], 1)

    def test_reset_preserves_backup_and_corruption_is_not_destroyed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProgressStore(folder)
            finish_lesson(store.progress, "hello", 100)
            store.save()
            backup = store.reset()
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["xp"], 25)
            self.assertEqual(ProgressStore(folder).progress["xp"], 0)
            store.path.write_text("broken-json", encoding="utf-8")
            restored = ProgressStore(folder)
            self.assertTrue(restored.warning)
            backups = list(Path(folder).glob("progress-backup-*.json"))
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "broken-json")

    def test_curriculum_steps_examples_and_sync(self):
        unit_lessons = [lesson for unit in UNITS for lesson in unit["lessons"]]
        self.assertEqual([l["id"] for l in unit_lessons], [l["id"] for l in LESSONS])
        self.assertEqual(
            [q["id"] for l in unit_lessons for q in l["questions"]],
            [q["id"] for q in QUESTIONS],
        )

        for unit in UNITS:
            self.assertNotRegex(unit["title"], r"^\[(초급|중급|고급|기출)\]", unit["id"])

        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "example_check.py"
            for lesson in unit_lessons:
                steps = lesson.get("steps") or []
                examples = lesson.get("examples") or []
                min_count = 4 if lesson["id"] in ("modules-lab", "files-io", "json-project") else 3
                self.assertGreaterEqual(len(steps), min_count, lesson["id"])
                self.assertGreaterEqual(len(examples), min_count, lesson["id"])
                if lesson.get("lang", "python") == "python":
                    for idx, ex in enumerate(examples, start=1):
                        script.write_text(ex["code"], encoding="utf-8")
                        res = run_workspace_script(script, folder, ex.get("stdin", ""), timeout=5)
                        self.assertTrue(res["ok"], f"{lesson['id']} ex {idx}: {res}")
                        self.assertEqual(
                            res["output"].replace("\r\n", "\n").strip(),
                            ex["output"].replace("\r\n", "\n").strip(),
                            f"{lesson['id']} ex {idx}",
                        )
                else:
                    for idx, ex in enumerate(examples, start=1):
                        self.assertTrue(bool(ex.get("code", "").strip()), f"{lesson['id']} ex {idx}")
                        self.assertTrue(bool(ex.get("output", "").strip()), f"{lesson['id']} ex {idx}")
                for q in lesson["questions"]:
                    self.assertTrue(bool(q.get("hint", "").strip()), q["id"])
                    self.assertNotRegex(json.dumps(q, ensure_ascii=False), r"\$O\(|\\log|\$[^$\n\\]{1,24}\$", q["id"])
                    if q["type"] == "order":
                        self.assertEqual(len(set(q["tokens"])), len(q["tokens"]), q["id"])
                        self.assertIsInstance(q.get("separator"), str, q["id"])

    def test_stage_midterms_unlocks_rewards_and_badges(self):
        midterm_units = [u for u in UNITS if u.get("kind") == "midterm"]
        self.assertEqual(len(midterm_units), 8)
        for u in midterm_units:
            lesson = u["lessons"][0]
            self.assertEqual(lesson.get("kind"), "midterm")
            self.assertEqual(len(lesson["questions"]), 8)

            prog = fresh_progress()
            self.assertFalse(is_unlocked(prog, lesson["id"]))
            tier_lessons = [
                l for l in LESSONS
                if l["lang"] == u["lang"] and l["level"] == u["level"] and l.get("kind") != "midterm"
            ]
            for prev in tier_lessons[:-1]:
                finish_lesson(prog, prev["id"], 80)
                self.assertFalse(is_unlocked(prog, lesson["id"]))
            finish_lesson(prog, tier_lessons[-1]["id"], 80)
            self.assertTrue(is_unlocked(prog, lesson["id"]))

            if (u["lang"], u["level"]) == ("python", "intro"):
                self.assertFalse(dict((n, ok) for n, _, _, ok in badges(prog))["입문 마스터"])
            if (u["lang"], u["level"]) == ("rust", "intro"):
                self.assertFalse(dict((n, ok) for n, _, _, ok in badges(prog))["러스트 입문 마스터"])

            self.assertEqual(finish_lesson(prog, lesson["id"], 100), 50)
            self.assertEqual(finish_lesson(prog, lesson["id"], 75), 10)
            bmap = {name: unlocked for name, _, _, unlocked in badges(prog)}
            if (u["lang"], u["level"]) == ("python", "intro"):
                self.assertTrue(bmap["입문 마스터"])
            elif (u["lang"], u["level"]) == ("python", "beginner"):
                self.assertTrue(bmap["초급 정복"])
            elif (u["lang"], u["level"]) == ("rust", "intro"):
                self.assertTrue(bmap["러스트 입문 마스터"])

    def test_tiered_curriculum_unlocks_and_badges(self):
        self.assertEqual((len(UNITS), len(LESSONS), len(QUESTIONS), len(SAMPLES)), (41, 114, 592, 20))
        progress = fresh_progress()
        self.assertFalse(is_unlocked(progress, "numbers"))
        for entry_id in (
            "hello",
            "str-slice-methods",
            "classes-basic",
            "recursion-dp",
            "eip-slice-ref",
            "cospro-lv2-count",
            "exam-log-csv",
            "exam-2d-prefix",
            "rust-hello",
            "rust-ownership-borrow",
            "rust-impl-methods",
            "rust-recursion-dp",
            "rust-exam-borrow-trace",
            "rust-exam-sliding-dp",
            "rust-exam-csv-report",
            "rust-exam-parametric",
        ):
            self.assertTrue(is_unlocked(progress, entry_id), entry_id)
        for blocked_id in (
            "regex-basic",
            "inheritance-super",
            "tree-graph-bfs",
            "eip-oop-trace",
            "cospro-lv2-sim",
            "exam-regex-json",
            "exam-bfs-maze",
            "rust-variables",
            "rust-option-struct",
            "rust-slice-tuple",
            "rust-lifetimes-errors",
            "rust-grid-bfs",
            "rust-exam-mock-final",
            "rust-exam-merge-report",
        ):
            self.assertFalse(is_unlocked(progress, blocked_id), blocked_id)

        finish_lesson(progress, "eip-slice-ref", 100)
        self.assertTrue(is_unlocked(progress, "eip-oop-trace"))
        self.assertFalse(is_unlocked(progress, "eip-func-scope"))

        # Rust track progresses independently across tiers from Python
        self.assertEqual(finish_lesson(progress, "rust-hello", 100), 25)
        self.assertTrue(is_unlocked(progress, "rust-variables"))
        self.assertFalse(is_unlocked(progress, "numbers"))
        finish_lesson(progress, "rust-impl-methods", 100)
        self.assertTrue(is_unlocked(progress, "rust-generics-traits"))
        finish_lesson(progress, "rust-exam-borrow-trace", 100)
        self.assertTrue(is_unlocked(progress, "rust-exam-enum-parser"))

        all_badges = badges(progress)
        self.assertEqual(len(all_badges), 22)
        badge_map_mid = {name: unlocked for name, _, _, unlocked in all_badges}
        self.assertTrue(badge_map_mid["러스트 첫 걸음"])
        self.assertFalse(badge_map_mid["러스트 완전 정복"])
        self.assertFalse(badge_map_mid["러스트 초급 정복"])
        self.assertFalse(badge_map_mid["러스트 중급 도약"])
        self.assertFalse(badge_map_mid["러스트 고급 마스터"])
        self.assertFalse(badge_map_mid["러스트 실기 마스터"])
        self.assertTrue(badge_map_mid["듀얼 트랙 입문"])

        rust_only = fresh_progress()
        finish_lesson(rust_only, "rust-hello", 100)
        rust_only_badges = {name: unlocked for name, _, _, unlocked in badges(rust_only)}
        self.assertFalse(rust_only_badges["듀얼 트랙 입문"])

        for lesson in LESSONS:
            if lesson.get("level") == "exam":
                progress["completed"][lesson["id"]] = {"date": "2026-04-02", "best": 100, "count": 1}
        badge_map = {name: unlocked for name, _, _, unlocked in badges(progress)}
        self.assertTrue(badge_map["기출 실전 마스터"])
        self.assertFalse(badge_map["초급 정복"])

    def test_legacy_pystep_migration_and_multilang_settings(self):
        with tempfile.TemporaryDirectory() as root:
            old_dir = Path(root) / "PyStep"
            new_dir = Path(root) / "CodeStep"
            old_dir.mkdir(parents=True, exist_ok=True)
            legacy_prog = fresh_progress()
            finish_lesson(legacy_prog, "hello", 100)
            legacy_prog["settings"].update(activeLang="rust", playgroundLang="rust", rustPath="C:\\fake\\rustc.exe")
            (old_dir / "progress.json").write_text(json.dumps(legacy_prog, ensure_ascii=False), encoding="utf-8")
            (old_dir / "draft.json").write_text(json.dumps({"code": "print(42)", "stdin": "abc", "sample": "hello"}), encoding="utf-8")

            migrated = ProgressStore(new_dir, legacy_folder=old_dir)
            self.assertEqual(migrated.progress["xp"], 25)
            self.assertIn("hello", migrated.progress["completed"])
            self.assertEqual(migrated.progress["settings"]["activeLang"], "rust")
            self.assertEqual(migrated.progress["settings"]["playgroundLang"], "rust")
            self.assertEqual(migrated.progress["settings"]["rustPath"], "C:\\fake\\rustc.exe")
            self.assertEqual(migrated.draft["code"], "print(42)")
            self.assertTrue((new_dir / "progress.json").is_file())

    def test_audit_regressions_slots_tokens_rust_unit1_and_perfect_count(self):
        qmap = {q["id"]: q for q in QUESTIONS}
        for lang in ("python", "rust"):
            slots = {}
            for q in QUESTIONS:
                if q.get("lang", "python") == lang and q["type"] in ("choice", "fill"):
                    ans = q["answer"] if isinstance(q["answer"], int) else q["options"].index(q["answer"])
                    slots[ans] = slots.get(ans, 0) + 1
            self.assertEqual(set(slots.keys()), {0, 1, 2, 3}, f"{lang}: {slots}")
            self.assertLessEqual(max(slots.values()) - min(slots.values()), 1, f"{lang}: {slots}")

        for qid in ("for-3", "rust-exam-sliding-dp-3"):
            self.assertGreaterEqual(len(qmap[qid]["tokens"]), 3, qid)
            self.assertGreaterEqual(len(qmap[qid]["answer"]), 3, qid)

        rust_unit1_prog = fresh_progress()
        rust_basics = next(u for u in UNITS if u["id"] == "rust-basics")
        for lesson in rust_basics["lessons"]:
            finish_lesson(rust_unit1_prog, lesson["id"], 80)
        badge_map = {name: unlocked for name, _, _, unlocked in badges(rust_unit1_prog)}
        self.assertTrue(badge_map["기초가 단단해요"])

        repeat_prog = fresh_progress()
        finish_lesson(repeat_prog, "hello", 100)
        self.assertEqual(repeat_prog["perfectCount"], 1)
        finish_lesson(repeat_prog, "hello", 100)
        self.assertEqual(repeat_prog["perfectCount"], 1)
        finish_lesson(repeat_prog, "numbers", 80)
        self.assertEqual(repeat_prog["perfectCount"], 1)
        finish_lesson(repeat_prog, "numbers", 100)
        self.assertEqual(repeat_prog["perfectCount"], 2)


if __name__ == "__main__":
    unittest.main()
