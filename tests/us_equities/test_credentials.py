from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from options_panel.us_equities.credential_store import CredentialError, load_credentials, save_credentials


@unittest.skipUnless(os.name == "nt", "Windows DPAPI")
class CredentialStorageTests(unittest.TestCase):
    def env_without_credentials(self):
        return mock.patch.dict(os.environ, {}, clear=False)

    def test_encrypted_roundtrip_missing_and_corrupt(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"ALPACA_API_KEY": "", "ALPACA_API_SECRET": ""}, clear=False
        ):
            # Empty explicit environment values are intentionally invalid, so remove
            # both keys to exercise only a temporary DPAPI file.
            os.environ.pop("ALPACA_API_KEY")
            os.environ.pop("ALPACA_API_SECRET")
            path = Path(directory) / "sample.dpapi"
            self.assertIsNone(load_credentials(path=path))
            save_credentials("FAKE-PAPER-KEY", "FAKE-SECRET", {"ok": True}, path=path)
            encrypted = path.read_bytes()
            self.assertNotIn(b"FAKE-PAPER-KEY", encrypted)
            self.assertNotIn(b"FAKE-SECRET", encrypted)
            self.assertEqual(load_credentials(path=path), ("FAKE-PAPER-KEY", "FAKE-SECRET"))
            path.write_bytes(b"invalid")
            with self.assertRaises(CredentialError):
                load_credentials(path=path)

    def test_failed_validation_preserves_previous_configuration(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"ALPACA_API_KEY": "", "ALPACA_API_SECRET": ""}, clear=False
        ):
            os.environ.pop("ALPACA_API_KEY")
            os.environ.pop("ALPACA_API_SECRET")
            path = Path(directory) / "sample.dpapi"
            save_credentials("FAKE-OLD", "FAKE-OLD-SECRET", {"ok": True}, path=path)
            before = path.read_bytes()
            with self.assertRaises(CredentialError):
                save_credentials("FAKE-NEW", "FAKE-NEW-SECRET", {"ok": False}, path=path)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()

