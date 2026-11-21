"""Curriculum consistency and the "자주 하는 실수" sections."""
import collections
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning import (LESSON_BY_ID, LESSONS, QUESTION_BY_ID, QUESTIONS, UNITS, compare_written_output, finish_lesson,  # noqa: E402
                      fresh_progress, is_unlocked)


class CurriculumConsistencyTests(unittest.TestCase):
    def test_units_lessons_and_questions_are_one_consistent_set(self):
        self.assertEqual(len(QUESTION_BY_ID), len(QUESTIONS), "question ids must be unique")
        unit_lesson_ids = [lesson["id"] for unit in UNITS for lesson in unit["lessons"]]
        self.assertEqual(sorted(unit_lesson_ids), sorted(LESSON_BY_ID))
        for unit in UNITS:
            for lesson in unit["lessons"]:
                # units point at the single lesson object, so content can never differ between screens
                self.assertIs(lesson, LESSON_BY_ID[lesson["id"]])
        for lesson in LESSONS:
            for question in lesson["questions"]:
                self.assertEqual(question, QUESTION_BY_ID[question["id"]], question["id"])
                self.assertEqual(question["lessonId"], lesson["id"])

    def test_error_unit_follows_decisions_and_unlocks_in_order(self):
        python_units = [unit["id"] for unit in UNITS if unit["lang"] == "python"]
        self.assertEqual(python_units.index("errors"), python_units.index("decisions") + 1)
        self.assertEqual([unit["number"] for unit in UNITS if unit["lang"] == "python"], list(range(1, len(python_units) + 1)))
        progress = fresh_progress()
        self.assertFalse(is_unlocked(progress, "error-reading"))
        for lesson_id in ("hello", "numbers", "variables", "strings", "types", "booleans", "compare", "conditions", "elif"):
            finish_lesson(progress, lesson_id, 100)
        self.assertTrue(is_unlocked(progress, "error-reading"))
        self.assertFalse(is_unlocked(progress, "error-common"))
        self.assertFalse(is_unlocked(progress, "lists"), "the next unit waits for the new error lessons")

    def test_every_intro_lesson_has_complete_pitfalls(self):
        intro = [lesson for lesson in LESSONS if lesson["level"] == "intro" and lesson.get("kind") != "midterm"]
        self.assertEqual(len(intro), 24 + 6)
        counts = collections.Counter()
        for lesson in intro:
            pitfalls = lesson.get("pitfalls") or []
            self.assertTrue(pitfalls, f"{lesson['id']} has no '자주 하는 실수'")
            for item in pitfalls:
                for field in ("title", "wrong", "fix", "why", "expect"):
                    self.assertTrue(str(item.get(field, "")).strip(), f"{lesson['id']}: {field}")
                if item["expect"] == "output":
                    self.assertIn("wrongOutput", item)
                else:
                    self.assertTrue(item.get("message"), f"{lesson['id']}: run tools/refresh_pitfalls.py")
                counts[lesson["lang"]] += 1
        self.assertEqual(counts["python"] + counts["rust"], 58)

    def test_every_lesson_has_rich_examples(self):
        # Each lesson got five times its original 3-4 examples, one per function/operator and then mixed uses.
        for lesson in LESSONS:
            examples = lesson.get("examples") or []
            self.assertGreaterEqual(len(examples), 15, lesson["id"])
            titles = [e["title"] for e in examples]
            self.assertEqual(len(titles), len(set(titles)), f"{lesson['id']}: duplicate example titles")
            for e in examples:
                for field in ("title", "code", "output", "note"):
                    self.assertTrue(str(e.get(field, "")).strip(), f"{lesson['id']} / {e.get('title')}: {field}")
        self.assertGreaterEqual(sum(len(l["examples"]) for l in LESSONS), 1515)

    def test_written_output_is_graded_like_an_answer_sheet(self):
        self.assertIsNone(compare_written_output("a  \r\n\nb\n\n", "a\n\nb"), "invisible trailing spaces and blank lines are ignored")
        self.assertEqual(compare_written_output("a\nc", "a\nb"), 2)
        self.assertEqual(compare_written_output("a", "a\nb"), 2, "a missing line is reported where it should start")
        self.assertEqual(compare_written_output("a\nb\nc", "a\nb"), 3)
        self.assertEqual(compare_written_output("[1,2]", "[1, 2]"), 1, "spaces between values count")

    def test_certificate_exam_units_practise_the_written_format(self):
        expected = {"exam-eip-trace": 5, "exam-eip-calc": 4, "exam-sec-lab": 7}
        units = {unit["id"]: unit for unit in UNITS}
        for unit_id, lesson_count in expected.items():
            unit = units[unit_id]
            self.assertEqual((unit["lang"], unit["level"], len(unit["lessons"])), ("python", "exam", lesson_count))
            for lesson in unit["lessons"]:
                written = [q for q in lesson["questions"] if q["type"] == "output"]
                self.assertGreaterEqual(len(written), 6, lesson["id"])
                self.assertEqual(lesson["questions"][-1]["type"], "code", lesson["id"])
        self.assertIn("실제 기출을 옮긴 것이 아니라", LESSON_BY_ID["eipx-string"]["body"])
        self.assertIn("코드를 쓰는 시험이 아니에요", LESSON_BY_ID["secx-perm"]["body"])

    def test_written_output_answers_are_what_the_programs_print(self):
        for question in QUESTIONS:
            if question["type"] != "output":
                continue
            process = subprocess.run([sys.executable, "-X", "utf8", "-c", question["code"]], capture_output=True, text=True,
                                     encoding="utf-8", timeout=30, cwd=str(ROOT))
            self.assertEqual(process.returncode, 0, question["id"] + process.stderr[-500:])
            self.assertIsNone(compare_written_output(process.stdout, question["answer"]), question["id"])

    def test_pitfalls_still_behave_as_described(self):
        # Re-runs every wrong/fixed pair through the real runners (rustc ones are skipped without rustc).
        process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools" / "refresh_pitfalls.py"), "--check"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, cwd=str(ROOT))
        self.assertEqual(process.returncode, 0, process.stdout[-3000:] + process.stderr[-2000:])

    def test_catalog_file_keeps_its_format(self):
        raw = (ROOT / "data" / "curriculum.json").read_bytes()
        self.assertIn(b"\r\n", raw[:20])
        text = raw.decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n", text)


if __name__ == "__main__":
    unittest.main()
