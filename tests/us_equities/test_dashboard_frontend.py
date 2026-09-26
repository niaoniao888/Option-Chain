from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DashboardFrontendTests(unittest.TestCase):
    def node_json(self, body: str):
        prefix = "const {pathToFileURL}=require('node:url');const path=require('node:path');"
        result = subprocess.run(["node", "-e", prefix + body], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20, check=True)
        return json.loads(result.stdout)

    def test_unified_frontend_module_contracts(self):
        result = subprocess.run(["node", "tests/test_ui.js"], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20, check=True)
        self.assertIn("Unified UI modules: PASS", result.stdout)

    def test_old_market_renderers_are_removed(self):
        for path in ("web/desktop", "web/mobile", "web/us-equities/app.js", "web/us-equities/style.css"):
            self.assertFalse((ROOT / path).exists(), path)

    def test_all_public_surfaces_use_one_shell(self):
        source = (ROOT / "src/options_panel/modules/registry.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('desktop_dir="app", mobile_dir="app"'), 2)

    def test_nested_esm_assets_are_declared(self):
        source = (ROOT / "src/options_panel/modules/registry.py").read_text(encoding="utf-8")
        for asset in ("core/state.js", "components/dashboard.js", "markets/registry.js"):
            self.assertIn(asset, source)

    def test_shell_is_read_only_and_has_three_views(self):
        html = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("data-panel="), 3)
        self.assertNotIn('method="POST"', html)

    def test_route_context_preserves_prefix_and_mode(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/markets/registry.js')));process.stdout.write(JSON.stringify(m.routeContext('/panel/us-equities/mobile/')));})();")
        self.assertEqual(result, {"market": "us-equities", "mode": "mobile", "basePath": "/panel"})

    def test_state_schema_migrates_legacy_sort_keys(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/core/state.js')));process.stdout.write(JSON.stringify(m.normalizeUi({priceSort:{key:'delta',direction:'desc'},rankSort:{key:'expiry_ms',direction:'asc'}})));})();")
        self.assertEqual(result["priceSort"]["key"], "exercise_probability_pct")
        self.assertEqual(result["rankSort"]["key"], "expiry")

    def test_retry_after_is_bounded(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/core/polling.js')));process.stdout.write(JSON.stringify([m.retryDelay({retryAfter:999}),m.retryDelay({retryAfter:-1})]));})();")
        self.assertEqual(result, [300000, 5000])

    def test_bitcoin_edge_metric_presentations(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/markets/bitcoin.js')));const a=m.createBitcoinAdapter({mode:'desktop'});process.stdout.write(JSON.stringify([a.annualHtml({open_interest:0}),a.probabilityHtml({open_interest:1,exercise_probability_pct:.01}),a.probabilityHtml({open_interest:1,exercise_probability_pct:99.99})]));})();")
        self.assertEqual(result, ["—", "&lt;0.1%", "&gt;99.9%"])

    def test_us_expiry_validation_rejects_impossible_dates(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/markets/us-equities.js')));process.stdout.write(JSON.stringify([m.validExpiryDate('2026-10-03'),m.validExpiryDate('2026-02-31')]));})();")
        self.assertEqual(result, [True, False])

    def test_pagination_is_bounded_and_preserves_empty_page(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/components/dashboard.js')));process.stdout.write(JSON.stringify([m.paginationItems(50,100),m.resolvedRankingPage(5,1,false)]));})();")
        self.assertLessEqual(len(result[0]), 7)
        self.assertEqual(result[1]["storedPage"], 5)

    def test_third_market_factory_is_registry_data(self):
        result = self.node_json("(async()=>{const m=await import(pathToFileURL(path.resolve('web/app/markets/registry.js')));m.registerMarketAdapter('third',o=>({id:'third',...o}),{label:'第三市场'});process.stdout.write(JSON.stringify([m.marketLabel('third'),m.createMarketAdapter({market:'third',mode:'desktop'}).id]));})();")
        self.assertEqual(result, ["第三市场", "third"])

    def test_playwright_dependency_is_locked(self):
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["packages"][""]["devDependencies"]["@playwright/test"], "1.55.1")

    def test_browser_ci_and_admin_separation_remain_explicit(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("browser-tests:", workflow)
        self.assertTrue((ROOT / "web/us-equities/admin.js").is_file())
        self.assertFalse((ROOT / "web/app/admin.js").exists())


if __name__ == "__main__":
    unittest.main()
