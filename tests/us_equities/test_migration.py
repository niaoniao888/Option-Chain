import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from options_panel.us_equities.guide_store import DEFAULT_SECTIONS, make_document


class MigrationTests(unittest.TestCase):
    def test_full_guide_validation_and_exclusive_atomic_copy(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            document = make_document(DEFAULT_SECTIONS, "2026-09-26T00:00:00Z")
            good = json.dumps(document)
            document["revision"] = "corrupt"
            (source / "options-guide.json").write_text(json.dumps(document), encoding="utf-8")
            command = [sys.executable, str(root / "scripts/migrate_us_data.py"),
                       "--source", str(source), "--destination", str(target), "--apply"]
            invalid = subprocess.run(command, cwd=root, capture_output=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse(target.exists())
            (source / "options-guide.json").write_text(good, encoding="utf-8")
            for _ in range(2):
                valid = subprocess.run(command, cwd=root, capture_output=True)
                self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual((target / "options-guide.json").read_text(encoding="utf-8"), good)
            self.assertEqual(list(target.glob(".migration-*")), [])
