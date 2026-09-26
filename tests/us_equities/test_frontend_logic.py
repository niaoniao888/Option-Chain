from __future__ import annotations
import json, subprocess, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
class FrontendLogicTests(unittest.TestCase):
    def run_module(self, body: str):
        script = "const {pathToFileURL}=require('node:url');const path=require('node:path');" + body
        completed = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20, check=True)
        return json.loads(completed.stdout)
    def test_expiry_validation_projection_and_labels(self):
        result = self.run_module(r'''(async()=>{const us=await import(pathToFileURL(path.resolve('web/app/markets/us-equities.js')));const now=Date.parse('2026-09-25T12:00:00Z');const raw={state:'ready',fetch_health:'healthy',market_status:'OPEN',server_time:new Date(now).toISOString(),fetched_age_seconds:0,market_status_valid_until_utc:new Date(now+60000).toISOString(),contracts:[{contract_symbol:'A',expiration_date:'2026-09-26',expires_at_utc:'2026-09-26T20:00:00Z',quote_valid_until_utc:new Date(now+1000).toISOString(),side:'CALL',strike:100,calculation_status:'calculated',annualized_pct:5,ranking_eligible:true,close_reference_eligible:false}]};const projected=us.projectUsSnapshot(raw,now);process.stdout.write(JSON.stringify({valid:us.validExpiryDate('2026-09-26'),bad:us.validExpiryDate('2026-02-31'),mode:projected.mode,label:us.stockLabel('AAPL')}));})();''')
        self.assertEqual(result, {"valid": True, "bad": False, "mode": "live", "label": "AAPL（苹果）"})
    def test_cross_symbol_sort_state_uses_current_object(self):
        result = self.run_module(r'''(async()=>{const state=await import(pathToFileURL(path.resolve('web/app/core/state.js')));const first=state.normalizeUi(),second=state.normalizeUi();state.applySort(first,'priceSort','annualized_pct');state.applySort(second,'priceSort','remaining_seconds');state.applySort(second,'rankSort','exercise_probability_pct');process.stdout.write(JSON.stringify({first:first.priceSort,second:second.priceSort,rank:second.rankSort}));})();''')
        self.assertEqual(result["first"], {"key": "annualized_pct", "direction": "desc"})
        self.assertEqual(result["second"], {"key": "remaining_seconds", "direction": "asc"})
        self.assertEqual(result["rank"], {"key": "exercise_probability_pct", "direction": "desc"})
if __name__ == "__main__": unittest.main()
