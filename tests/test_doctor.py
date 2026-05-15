import unittest
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import doctor


class DoctorTests(unittest.TestCase):
    def test_parse_adb_devices_detects_online_device(self):
        output = "List of devices attached\n10AFBC22FT008G3\tdevice\n"
        self.assertEqual(doctor.parse_adb_devices(output), ["10AFBC22FT008G3"])

    def test_parse_adb_devices_ignores_unauthorized_devices(self):
        output = "List of devices attached\nabc\tunauthorized\nxyz\toffline\n"
        self.assertEqual(doctor.parse_adb_devices(output), [])

    def test_check_env_reports_missing_token_without_leaking_values(self):
        checks = doctor.check_env({"ANTHROPIC_MODEL": "deepseek-v4-flash"})
        token_check = next(c for c in checks if c["name"] == "ANTHROPIC_AUTH_TOKEN")
        model_check = next(c for c in checks if c["name"] == "ANTHROPIC_MODEL")

        self.assertFalse(token_check["ok"])
        self.assertIn("missing", token_check["message"])
        self.assertTrue(model_check["ok"])
        self.assertNotIn("sk-", str(checks))

    @patch("doctor.time.sleep")
    @patch("doctor._run")
    def test_check_ui_dump_retries_transient_failure(self, run, _sleep):
        failed = Mock(returncode=1, stderr="ERROR: could not get idle state.", stdout="")
        succeeded = Mock(returncode=0, stderr="", stdout="UI hierarchy dumped")
        run.side_effect = [failed, succeeded]

        result = doctor.check_ui_dump("adb")

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
