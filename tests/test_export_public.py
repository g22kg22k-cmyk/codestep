"""tools/export_public.py: only allowed files are copied, and personal details block the export."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("export_public", ROOT / "tools" / "export_public.py")
export_public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_public)
# A fresh clone has no dist/CodeStep.exe; then only the source part of the export is tested.
EXE_READY = export_public.exe_problem() is None


class ExportPublicTests(unittest.TestCase):
    def test_personal_details_are_detected(self):
        # Built at run time so this test file itself never contains such a value.
        user_path = "C:" + "\\Users\\" + "someone" + "\\Documents\\x.txt"
        email = "someone" + "@" + "mailhost.co.kr"  # an ordinary domain; reserved example domains are allowed
        literals = export_public.personal_patterns()
        with tempfile.TemporaryDirectory() as tmp:
            for content in (user_path, email, str(Path.home()), str(ROOT)):
                sample = Path(tmp) / "sample.py"
                sample.write_text(f"value = {content!r}\n", encoding="utf-8")
                self.assertTrue(export_public.scan(sample, literals), content)
            utf16 = Path(tmp) / "sample.bin"
            utf16.write_bytes(user_path.encode("utf-16-le"))
            self.assertTrue(export_public.scan(utf16, literals), "UTF-16 text inside binary files is checked too")
            clean = Path(tmp) / "clean.py"
            reserved = "coder" + "@" + "example.com, a" + "@" + "mail.example.org"
            clean.write_text(f'folder = "%LOCALAPPDATA%\\\\CodeStep"\nhome = "C:\\\\Users\\\\..."\nteach = "{reserved}"\n', encoding="utf-8")
            self.assertEqual(export_public.scan(clean, literals), [], "addresses at reserved example domains are fine")
            look_alike = Path(tmp) / "look_alike.py"
            look_alike.write_text('x = "a' + '@' + 'example.com.evil.net"\n', encoding="utf-8")
            self.assertTrue(export_public.scan(look_alike, literals), "only the reserved domain itself is allowed")

    def test_an_exe_that_cannot_be_inspected_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "CodeStep.exe"
            fake.write_bytes(b"MZ not a real program")
            self.assertTrue(export_public.scan(fake, export_public.personal_patterns()))

    def test_export_copies_only_allowed_files_and_protects_other_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "public"
            self.assertEqual(export_public.export(target, include_exe=EXE_READY), 0)
            names = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
            for required in ("data/curriculum.json", "setup-build-python.ps1", "LICENSE", "start.bat", export_public.MARKER):
                self.assertIn(required, names)
            if EXE_READY:
                self.assertIn("CodeStep.exe", names, "the folder must run on a PC without Python")
            self.assertEqual([n for n in names if n.endswith(".exe")], ["CodeStep.exe"] if EXE_READY else [])
            for forbidden in (".build-python", "dist", "build", "test-results", "__pycache__", "public", "server.py"):
                self.assertFalse(any(name == forbidden or name.startswith(forbidden + "/") or f"/{forbidden}/" in name
                                     for name in names), forbidden)
            self.assertFalse(any(name.endswith(".pyc") for name in names))
            with self.assertRaises(SystemExit):
                export_public.export(target, include_exe=EXE_READY)  # not empty, no --replace

            # A blocked update must leave the previous copy exactly as it was.
            with patch.object(export_public, "personal_patterns", return_value=["CodeStep"]):
                with self.assertRaises(SystemExit):
                    export_public.export(target, replace=True, include_exe=False)
            self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}, names)

            self.assertEqual(export_public.export(target, replace=True, include_exe=EXE_READY), 0)
            other = Path(tmp) / "someone-elses-folder"
            other.mkdir()
            (other / "keep.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(SystemExit):
                export_public.export(other, replace=True, include_exe=False)
            self.assertTrue((other / "keep.txt").exists(), "a folder this tool did not make is never emptied")


if __name__ == "__main__":
    unittest.main()
