import copy
import json
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from options_panel.manage import main
from options_panel.runtime_archive import backup, restore
from options_panel.us_equities.guide_store import GuideStore, make_document
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

    def test_restore_rolls_back_each_replace_and_backup_removal_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "complete.tar.gz"
            new_watch = WatchlistStore._encode(["NEW"])
            sections = copy.deepcopy(GuideStore(root / "new-guide.json").get()["sections"])
            sections[0]["topics"][0]["body"] = "new guide"
            new_document = make_document(sections, "new")
            new_guide = GuideStore._encode(new_document)
            sections = copy.deepcopy(sections)
            sections[0]["topics"][0]["body"] = "old guide"
            old_document = make_document(sections, "old")
            old_guide = GuideStore._encode(old_document)
            sections = copy.deepcopy(sections)
            sections[0]["topics"][0]["body"] = "older guide"
            older_document = make_document(sections, "older")
            older_guide = GuideStore._encode(older_document)
            with tarfile.open(archive, "w:gz") as bundle:
                for name, payload in (
                    ("watchlist.json", new_watch),
                    ("options-guide.json", new_guide),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))

            for failure_kind, failure_index in (
                ("replace", 1),
                ("replace", 2),
                ("unlink", 1),
                ("unlink", 2),
            ):
                runtime = root / f"runtime-{failure_kind}-{failure_index}"
                runtime.mkdir()
                originals = {
                    "watchlist.json": WatchlistStore._encode(["OLD"]),
                    "watchlist.json.bak": WatchlistStore._encode(["OLDER"]),
                    "options-guide.json": old_guide,
                    "options-guide.json.bak": older_guide,
                }
                for name, payload in originals.items():
                    (runtime / name).write_bytes(payload)
                original_replace = __import__("os").replace
                original_unlink = Path.unlink
                replace_count = 0
                unlink_count = 0

                def failing_replace(source, destination):
                    nonlocal replace_count
                    replace_count += 1
                    if failure_kind == "replace" and replace_count == failure_index:
                        raise OSError("injected replace failure")
                    return original_replace(source, destination)

                def failing_unlink(path, *args, **kwargs):
                    nonlocal unlink_count
                    if path.parent == runtime and path.name.endswith(".bak"):
                        unlink_count += 1
                        if failure_kind == "unlink" and unlink_count == failure_index:
                            raise OSError("injected unlink failure")
                    return original_unlink(path, *args, **kwargs)

                with self.subTest(kind=failure_kind, step=failure_index), \
                     mock.patch("options_panel.runtime_archive.os.replace", side_effect=failing_replace), \
                     mock.patch("pathlib.Path.unlink", new=failing_unlink), \
                     self.assertRaises(OSError):
                    restore(archive, runtime)
                self.assertEqual(
                    originals,
                    {name: (runtime / name).read_bytes() for name in originals},
                )
                self.assertFalse(list(runtime.glob(".restore-recovery-*")))

            successful = root / "runtime-success"
            successful.mkdir()
            for name, payload in {
                "watchlist.json": WatchlistStore._encode(["OLD"]),
                "watchlist.json.bak": WatchlistStore._encode(["OLDER"]),
                "options-guide.json": old_guide,
                "options-guide.json.bak": older_guide,
            }.items():
                (successful / name).write_bytes(payload)
            restore(archive, successful)
            self.assertEqual((successful / "watchlist.json").read_bytes(), new_watch)
            self.assertEqual((successful / "options-guide.json").read_bytes(), new_guide)
            self.assertFalse((successful / "watchlist.json.bak").exists())
            self.assertFalse((successful / "options-guide.json.bak").exists())

    def test_restore_persistent_replace_failure_restores_or_preserves_recovery_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / "runtime"
            runtime.mkdir()
            old_watch = WatchlistStore._encode(["OLD"])
            sections = copy.deepcopy(GuideStore(root / "old-guide.json").get()["sections"])
            sections[0]["topics"][0]["body"] = "old guide"
            old_document = make_document(sections, "old")
            old_guide = GuideStore._encode(old_document)
            sections = copy.deepcopy(sections)
            sections[0]["topics"][0]["body"] = "new guide"
            new_document = make_document(sections, "new")
            new_guide = GuideStore._encode(new_document)
            originals = {
                "watchlist.json": old_watch,
                "options-guide.json": old_guide,
            }
            for name, payload in originals.items():
                (runtime / name).write_bytes(payload)
            archive = root / "complete.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for name, payload in (
                    ("watchlist.json", WatchlistStore._encode(["NEW"])),
                    ("options-guide.json", new_guide),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))

            with mock.patch(
                "options_panel.runtime_archive.os.replace",
                side_effect=OSError("persistent replace failure"),
            ), self.assertRaises(OSError):
                restore(archive, runtime)
            self.assertEqual(
                originals,
                {name: (runtime / name).read_bytes() for name in originals},
            )
            self.assertFalse(list(runtime.glob(".restore-recovery-*")))

            original_copy2 = __import__("shutil").copy2

            def fail_recovery_copy(source, destination, *args, **kwargs):
                if Path(source).parent.name.startswith(".restore-recovery-"):
                    raise OSError("persistent rollback copy failure")
                return original_copy2(source, destination, *args, **kwargs)

            with mock.patch(
                "options_panel.runtime_archive.os.replace",
                side_effect=OSError("persistent replace failure"),
            ), mock.patch(
                "options_panel.runtime_archive.shutil.copy2",
                side_effect=fail_recovery_copy,
            ), self.assertRaisesRegex(RuntimeError, "恢复副本保留"):
                restore(archive, runtime)
            recovery_dirs = list(runtime.glob(".restore-recovery-*"))
            self.assertEqual(len(recovery_dirs), 1)
            for name, payload in originals.items():
                self.assertEqual((recovery_dirs[0] / name).read_bytes(), payload)

            empty_runtime = root / "runtime-empty"
            empty_runtime.mkdir()
            original_replace = __import__("os").replace
            replace_count = 0

            def fail_second_replace(source, destination):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("second replace failed")
                return original_replace(source, destination)

            with mock.patch(
                "options_panel.runtime_archive.os.replace",
                side_effect=fail_second_replace,
            ), self.assertRaises(OSError):
                restore(archive, empty_runtime)
            self.assertFalse((empty_runtime / "watchlist.json").exists())
            self.assertFalse((empty_runtime / "options-guide.json").exists())

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
