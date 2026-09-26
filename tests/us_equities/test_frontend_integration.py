from __future__ import annotations
import subprocess, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
class UnifiedFrontendIntegrationTests(unittest.TestCase):
    def test_esm_bootstrap_and_read_only_shell(self):
        result = subprocess.run(["node", "tests/test_bootstrap.js"], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20, check=True)
        self.assertIn("Unified module bootstrap: PASS", result.stdout)
        html = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertNotIn('method="POST"', html)
    def test_admin_remains_separate_and_keeps_revision_guards(self):
        admin = (ROOT / "web/us-equities/admin.js").read_text(encoding="utf-8")
        self.assertIn("history.replaceState", admin)
        self.assertIn('"If-Match":watchRevision', admin)
        self.assertIn('"If-Match":guideDocument.revision', admin)
if __name__ == "__main__": unittest.main()
