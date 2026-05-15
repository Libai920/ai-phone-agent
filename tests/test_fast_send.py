import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fast_agent


class FastSendTests(unittest.TestCase):
    @patch("fast_agent.time.sleep")
    @patch("fast_agent._find_and_click")
    @patch("fast_agent.get_ui_state")
    @patch("fast_agent.execute")
    @patch("fast_agent.launch_and_wait")
    def test_wechat_file_transfer_uses_chinese_search_button(
        self,
        launch_and_wait,
        execute,
        get_ui_state,
        find_and_click,
        _sleep,
    ):
        search_nodes = [{
            "text": "",
            "content_desc": "搜索",
            "resource_id": "",
            "class": "android.widget.ImageButton",
            "clickable": True,
            "focusable": False,
        }]
        search_result_nodes = [{
            "text": "文件传输助手",
            "content_desc": "",
            "resource_id": "com.tencent.mm:id/title",
            "class": "android.widget.TextView",
            "clickable": True,
            "focusable": False,
        }]
        chat_nodes = [{
            "text": "",
            "content_desc": "",
            "resource_id": "com.tencent.mm:id/input",
            "class": "android.widget.EditText",
            "clickable": True,
            "focusable": True,
        }]
        send_nodes = [{
            "text": "发送",
            "content_desc": "",
            "resource_id": "com.tencent.mm:id/send",
            "class": "android.widget.Button",
            "clickable": True,
            "focusable": False,
        }]

        launch_and_wait.return_value = search_nodes
        get_ui_state.side_effect = [search_result_nodes, chat_nodes, send_nodes]
        find_and_click.side_effect = [False, True]

        ok = fast_agent.fast_send(
            {"type": "send", "target": "微信文件传输助手", "text": "1"},
            [],
        )

        self.assertTrue(ok)
        launch_and_wait.assert_called_once_with(app="微信")
        input_texts = [
            call.args[1]["text"]
            for call in execute.call_args_list
            if call.args[1].get("action") == "input"
        ]
        self.assertEqual(input_texts, ["文件传输助手", "1"])


if __name__ == "__main__":
    unittest.main()
