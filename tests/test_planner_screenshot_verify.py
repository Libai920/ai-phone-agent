import unittest
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import planner


class ScreenshotVerificationTests(unittest.TestCase):
    def test_verify_screenshot_action_success_response(self):
        block = Mock()
        block.text = '{"ok": true, "message": "Search result page is visible"}'
        client = Mock()
        client.messages.create.return_value.content = [block]

        with patch("planner._get_client", return_value=client):
            result = planner.verify_screenshot_action(
                task="搜索大模型教程",
                action={"action": "input", "text": "大模型教程"},
                assertion={"text_contains": "大模型教程"},
                screenshot_b64="abc123",
            )

        self.assertEqual(result, {
            "ok": True,
            "message": "Search result page is visible",
        })
        call = client.messages.create.call_args.kwargs
        self.assertEqual(call["max_tokens"], 512)
        self.assertIn("verify whether the last action succeeded", call["system"])

    def test_verify_screenshot_action_failure_response(self):
        block = Mock()
        block.text = '{"ok": false, "message": "The expected text is not visible"}'
        client = Mock()
        client.messages.create.return_value.content = [block]

        with patch("planner._get_client", return_value=client):
            result = planner.verify_screenshot_action(
                task="搜索大模型教程",
                action={"action": "input", "text": "大模型教程"},
                assertion={"text_contains": "大模型教程"},
                screenshot_b64="abc123",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "The expected text is not visible")


if __name__ == "__main__":
    unittest.main()
