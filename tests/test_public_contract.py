from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urljoin, urlparse

from fastapi.testclient import TestClient

from options_panel.api import create_app
from options_panel.config import Settings
from options_panel.content.guide_store import GuideStore
from options_panel.runtime.refresher import ProcessLock

ROOT = Path(__file__).resolve().parents[1]


class PublicContractTests(unittest.TestCase):
    def test_all_page_assets_resolve_under_root_and_prefix(self):
        import re
        for prefix in ("", "/options", "/site/bitcoin/options"):
            settings = Settings(ROOT, base_path=prefix, collector_enabled=False)
            with TestClient(create_app(settings)) as client:
                for page in ("/", "/bitcoin/desktop/", "/bitcoin/mobile/"):
                    url = prefix + page
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200)
                    for asset in re.findall(r'(?:src|href)="([^"#]+\.(?:js|css))"', response.text):
                        asset_url = urlparse(urljoin("http://testserver" + url, asset)).path
                        self.assertEqual(client.get(asset_url).status_code, 200, asset_url)
                        self.assertTrue(asset_url.startswith(prefix + "/"))

    def test_public_writes_files_and_bad_hosts_are_rejected(self):
        with TestClient(create_app(Settings(ROOT, collector_enabled=False))) as client:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                self.assertEqual(client.request(method, "/api/v1/bitcoin/options-guide", json={}).status_code, 405)
            for url in ("/content/options-guide.json", "/runtime/logs/options-panel.log", "/src/options_panel/config.py", "/bitcoin/shared/unknown.py"):
                self.assertEqual(client.get(url).status_code, 404)
            self.assertEqual(client.get("/healthz", headers={"host": "untrusted.invalid"}).status_code, 400)
            self.assertIn("frame-ancestors 'self'", client.get("/").headers["content-security-policy"])

    def test_process_lock_excludes_an_actual_child_process(self):
        code = "from pathlib import Path; import sys; from options_panel.runtime.refresher import ProcessLock; lock=ProcessLock(Path(sys.argv[1])); lock.acquire(); lock.release()"
        with tempfile.TemporaryDirectory() as directory:
            lock = ProcessLock(Path(directory) / "collector.lock")
            lock.acquire()
            try:
                child = subprocess.run([sys.executable, "-c", code, str(lock.path)], capture_output=True, timeout=10)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn(b"already active", child.stderr)
            finally:
                lock.release()
            child = subprocess.run([sys.executable, "-c", code, str(lock.path)], capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)

    def test_shipped_guide_has_unique_ids_and_plain_text(self):
        document = GuideStore(ROOT / "content" / "options-guide.json").get()
        ids = set()
        for section in document["sections"]:
            self.assertNotIn(section["id"], ids)
            ids.add(section["id"])
            for topic in section["topics"]:
                self.assertNotIn(topic["id"], ids)
                ids.add(topic["id"])
                self.assertTrue(topic["body"].strip())

    def test_packaging_keeps_runtime_source_not_runtime_output(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("release_packager", ROOT / "scripts" / "package_release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        files = [p.relative_to(ROOT).as_posix() for p in module.source_files()]
        self.assertIn("src/options_panel/runtime/snapshot.py", files)
        self.assertTrue(all(not p.startswith(("runtime/", ".venv/", "dist/")) for p in files))


if __name__ == "__main__":
    unittest.main()
