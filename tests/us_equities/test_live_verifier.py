import importlib.util
import unittest
from pathlib import Path


class LiveVerifierTests(unittest.TestCase):
    def test_no_probabilities_cannot_pass_live_acceptance(self):
        path = Path(__file__).resolve().parents[2] / "scripts/verify_us_live.py"
        spec = importlib.util.spec_from_file_location("verify_us_live", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        snapshot = {"underlying_price": 100, "contracts": [{
            "strike": 110, "side": "CALL", "bid": 1,
            "annualized_pct": 365, "period_return_pct": 1,
            "expires_at_utc": "2026-09-27T00:00:00Z",
            "calculation_basis_utc": "2026-09-26T00:00:00Z",
            "exercise_probability_pct": None,
        }]}
        with self.assertRaisesRegex(ValueError, "probabilities"):
            module.verify(snapshot)
