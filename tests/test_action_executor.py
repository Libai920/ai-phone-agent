import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import action_executor


class ExecuteResultTests(unittest.TestCase):
    def setUp(self):
        self.node = {
            "class": "android.widget.TextView",
            "text": "知乎",
            "content_desc": "",
            "resource_id": "com.zhihu.android:id/title",
            "bounds": "[100,200][300,400]",
            "clickable": True,
            "focusable": False,
            "scrollable": False,
            "enabled": True,
        }

    @patch("action_executor.time.sleep")
    @patch("action_executor.adb")
    def test_click_returns_structured_result_with_hit_node(self, adb, _sleep):
        result = action_executor.execute([self.node], {
            "action": "click",
            "target": {"text": "知乎"},
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "click")
        self.assertEqual(result["hit"], self.node)
        self.assertIn("知乎", result["message"])
        adb.assert_called_once_with("shell", "input", "tap", "200", "300")

    @patch("action_executor.input_text")
    def test_input_returns_structured_result(self, input_text):
        result = action_executor.execute([], {"action": "input", "text": "你好"})

        self.assertEqual(result, {
            "ok": True,
            "action": "input",
            "hit": None,
            "message": "input text",
        })
        input_text.assert_called_once_with("你好")

    @patch("action_executor.press_back")
    def test_back_returns_structured_result(self, press_back):
        result = action_executor.execute([], {"action": "back"})

        self.assertEqual(result, {
            "ok": True,
            "action": "back",
            "hit": None,
            "message": "pressed back",
        })
        press_back.assert_called_once_with()

    @patch("action_executor.launch_app")
    def test_launch_returns_structured_result(self, launch_app):
        result = action_executor.execute([], {
            "action": "launch",
            "app": "知乎",
        })

        self.assertEqual(result, {
            "ok": True,
            "action": "launch",
            "hit": None,
            "message": "launched 知乎",
        })
        launch_app.assert_called_once_with(package="", app="知乎")

    def test_unknown_action_raises_runtime_error_for_replanning(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown action"):
            action_executor.execute([], {"action": "dance"})


if __name__ == "__main__":
    unittest.main()
