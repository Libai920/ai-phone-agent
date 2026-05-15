import unittest

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fast_agent import parse_intent


class ParseIntentTests(unittest.TestCase):
    def test_open_app(self):
        self.assertEqual(parse_intent("打开知乎"), {"type": "open", "app": "知乎"})

    def test_back(self):
        self.assertEqual(parse_intent("返回"), {"type": "back"})

    def test_research_in_app(self):
        self.assertEqual(
            parse_intent("在B站搜索大模型教程"),
            {"type": "research", "app": "B站", "query": "大模型教程"},
        )

    def test_pick_nth(self):
        self.assertEqual(parse_intent("点第1个"), {"type": "pick_nth", "n": 1})

    def test_send_in_app_with_target(self):
        self.assertEqual(
            parse_intent("在QQ里给文件传输助手发你好"),
            {"type": "send", "app": "QQ", "target": "文件传输助手", "text": "你好"},
        )

    def test_send_to_wechat_file_transfer_assistant(self):
        self.assertEqual(
            parse_intent("给微信文件传输助手发1"),
            {"type": "send", "target": "微信文件传输助手", "text": "1"},
        )


if __name__ == "__main__":
    unittest.main()
