from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from options_panel.api import create_app
from options_panel.config import Settings
from options_panel.runtime.snapshot import DashboardState


class ApiTests(unittest.TestCase):
    def app(self, base=""):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "content").mkdir()
        (root / "content" / "options-guide.json").write_text(json.dumps({"revision":"r1","updated_at":"2026-09-26T00:00:00Z","sections":[]}), encoding="utf-8")
        source_root = Path(__file__).resolve().parents[1]
        settings = Settings(root, base_path=base, collector_enabled=False)
        object.__setattr__(settings, "app_root", source_root)
        state = DashboardState()
        # Keep the copied web tree but direct guide data to the temporary document.
        import os
        old = os.environ.get("OPTIONS_DATA_DIR")
        os.environ["OPTIONS_DATA_DIR"] = str(root / "content")
        self.addCleanup(lambda: os.environ.__setitem__("OPTIONS_DATA_DIR", old) if old is not None else os.environ.pop("OPTIONS_DATA_DIR", None))
        self.addCleanup(temp.cleanup)
        return create_app(settings, state), state

    def test_root_routes_aliases_and_writes(self):
        app, state = self.app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/bitcoin/desktop", follow_redirects=False).headers["location"], "/bitcoin/desktop/")
            self.assertEqual(client.get("/bitcoin/desktop/").status_code, 200)
            self.assertEqual(client.get("/bitcoin/mobile/").status_code, 200)
            self.assertEqual(client.get("/api/snapshot").json(), client.get("/api/v1/bitcoin/snapshot").json())
            self.assertEqual(client.get("/api/options-guide").json()["revision"], "r1")
            self.assertEqual(client.put("/api/options-guide", json={}).status_code, 405)
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/readyz").status_code, 503)
            state.commit_catalog([]); state.commit_market({}, 85000, 1_700_000_000_000, {}, {})
            self.assertEqual(client.get("/readyz").status_code, 200)

    def test_base_prefix_and_module_links(self):
        app, _ = self.app("/option-panel")
        with TestClient(app) as client:
            self.assertEqual(client.get("/").status_code, 404)
            self.assertEqual(client.get("/option-panel/").status_code, 200)
            response = client.get("/option-panel/bitcoin/desktop", follow_redirects=False)
            self.assertEqual((response.status_code, response.headers["location"]), (308, "/option-panel/bitcoin/desktop/"))
            modules = client.get("/option-panel/api/v1/modules").json()
            self.assertEqual(modules[0]["desktop_path"], "/option-panel/bitcoin/desktop/")
            self.assertEqual(client.get("/option-panel/api/snapshot").status_code, 200)


if __name__ == "__main__":
    unittest.main()
