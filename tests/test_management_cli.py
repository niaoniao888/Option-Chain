import json
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from options_panel.manage import main
from options_panel.runtime_archive import backup, restore
from options_panel.us_equities.guide_store import GuideStore
from options_panel.us_equities.watchlist_store import WatchlistStore


class ManagementCliTests(unittest.TestCase):
    def test_watchlist_revision_and_guide_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            current = WatchlistStore(data / "watchlist.json").get()
            self.assertEqual(main(["--data-dir", str(data), "watchlist", "revision"]), 0)
            self.assertEqual(main(["--data-dir", str(data), "watchlist", "add", "AAPL", "--revision", current["revision"]]), 0)
            export = root / "guide.json"
            self.assertEqual(main(["--data-dir", str(data), "guide", "export", str(export)]), 0)
            document = json.loads(export.read_text(encoding="utf-8"))
            self.assertEqual(main(["--data-dir", str(data), "guide", "revision"]), 0)
            document["sections"][0]["topics"][0]["body"] = "Linux 导入测试"
            export.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            raw_output = io.BytesIO()
            ascii_stdout = io.TextIOWrapper(raw_output, encoding="ascii", errors="strict")
            with mock.patch("sys.stdout", ascii_stdout):
                result = main(["--data-dir", str(data), "guide", "import", str(export), "--revision", document["revision"]])
                ascii_stdout.flush()
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(raw_output.getvalue().decode("ascii"))["sections"][0]["topics"][0]["body"], "Linux 导入测试")
            self.assertEqual(GuideStore(data / "options-guide.json").get()["sections"][0]["topics"][0]["body"], "Linux 导入测试")

    def test_runtime_archive_rejects_traversal_and_restores(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / "runtime"; runtime.mkdir()
            watch = b'{"symbols":["SPCX"]}\n'
            guide = GuideStore._encode(GuideStore(runtime / "unused.json").get())
            (runtime / "watchlist.json").write_bytes(watch)
            (runtime / "options-guide.json").write_bytes(guide)
            (runtime / "collector.lock").write_text("excluded", encoding="utf-8")
            archive = root / "backup.tar.gz"
            backup(runtime, archive)
            (runtime / "watchlist.json").write_text('{"symbols":["AAPL"]}\n', encoding="utf-8")
            restore(archive, runtime)
            self.assertEqual(json.loads((runtime / "watchlist.json").read_text(encoding="utf-8"))["symbols"], ["SPCX"])
            self.assertEqual((runtime / "collector.lock").read_text(encoding="utf-8"), "excluded")
            bad = root / "bad.tar.gz"
            with tarfile.open(bad, "w:gz") as bundle:
                for name, payload in (("watchlist.json", watch), ("options-guide.json", guide)):
                    info = tarfile.TarInfo(name); info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))
                info = tarfile.TarInfo("../escape"); info.size = 0; bundle.addfile(info)
            with self.assertRaises(ValueError):
                restore(bad, runtime)

            malformed = root / "malformed.tar.gz"
            with tarfile.open(malformed, "w:gz") as bundle:
                payload = b"{bad"
                info = tarfile.TarInfo("watchlist.json"); info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))
                info = tarfile.TarInfo("options-guide.json"); info.size = len(guide)
                bundle.addfile(info, io.BytesIO(guide))
            with self.assertRaises(ValueError):
                restore(malformed, runtime)
            self.assertEqual(json.loads((runtime / "watchlist.json").read_text(encoding="utf-8"))["symbols"], ["SPCX"])

            for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                unsafe = root / f"link-{kind!r}.tar.gz"
                with tarfile.open(unsafe, "w:gz") as bundle:
                    for name, payload in (("watchlist.json", watch), ("options-guide.json", guide)):
                        info = tarfile.TarInfo(name); info.size = len(payload)
                        bundle.addfile(info, io.BytesIO(payload))
                    info = tarfile.TarInfo("watchlist.json.bak"); info.type = kind; info.linkname = "outside"
                    bundle.addfile(info)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    restore(unsafe, runtime)

            duplicate = root / "duplicate.tar.gz"
            with tarfile.open(duplicate, "w:gz") as bundle:
                payload = b'{"symbols":["SPCX"]}'
                for _ in range(2):
                    info = tarfile.TarInfo("watchlist.json"); info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))
                info = tarfile.TarInfo("options-guide.json"); info.size = len(guide)
                bundle.addfile(info, io.BytesIO(guide))
            with self.assertRaises(ValueError):
                restore(duplicate, runtime)

    def test_restore_requires_both_primary_documents_before_any_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); runtime = root / "runtime"; runtime.mkdir()
            watch = WatchlistStore._encode(["SPCX"])
            guide = GuideStore._encode(GuideStore(runtime / "unused.json").get())
            (runtime / "watchlist.json").write_bytes(watch)
            (runtime / "options-guide.json").write_bytes(guide)
            before = {name: (runtime / name).read_bytes() for name in ("watchlist.json", "options-guide.json")}

            for label, entries in (
                ("empty", {}),
                ("watchlist-only", {"watchlist.json": watch}),
                ("guide-only", {"options-guide.json": guide}),
            ):
                archive = root / f"{label}.tar.gz"
                with tarfile.open(archive, "w:gz") as bundle:
                    for name, payload in entries.items():
                        info = tarfile.TarInfo(name); info.size = len(payload)
                        bundle.addfile(info, io.BytesIO(payload))
                with self.subTest(label=label), self.assertRaises(ValueError):
                    restore(archive, runtime)
                self.assertEqual(before, {name: (runtime / name).read_bytes() for name in before})

            complete = root / "complete.tar.gz"
            with tarfile.open(complete, "w:gz") as bundle:
                for name, payload in (("watchlist.json", watch), ("options-guide.json", guide)):
                    info = tarfile.TarInfo(name); info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))
            with mock.patch("options_panel.runtime_archive.MAX_TAR_BYTES", 512), self.assertRaises(ValueError):
                restore(complete, runtime)
            self.assertEqual(before, {name: (runtime / name).read_bytes() for name in before})

    def test_release_source_whitelist_excludes_private_and_generated_files(self):
        from scripts.package_release import source_files
        project = Path(__file__).resolve().parents[1]
        relatives = {path.relative_to(project).as_posix() for path in source_files()}
        self.assertIn("scripts/options-panel.sh", relatives)
        self.assertIn("src/options_panel/runtime/snapshot.py", relatives)
        self.assertNotIn(".env", relatives)
        self.assertFalse(any(path.startswith(("runtime/", "dist/", "archive2.0/")) for path in relatives))
        ignore = (project / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/backups/", ignore)
        self.assertIn("/guide-edit.json", ignore)
        self.assertIn("/guide-edit.json.bak", ignore)


if __name__ == "__main__":
    unittest.main()
