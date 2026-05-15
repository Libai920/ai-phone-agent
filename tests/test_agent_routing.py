import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent


class AgentRoutingTests(unittest.TestCase):
    def test_visual_analysis_tasks_prefer_screenshot(self):
        self.assertTrue(agent._prefers_screenshot("分析这个页面"))
        self.assertTrue(agent._prefers_screenshot("看看哪个结果更好"))
        self.assertTrue(agent._prefers_screenshot("比较一下这些结果"))

    def test_simple_control_tasks_do_not_prefer_screenshot(self):
        self.assertFalse(agent._prefers_screenshot("打开知乎"))
        self.assertFalse(agent._prefers_screenshot("返回"))
        self.assertFalse(agent._prefers_screenshot("给微信文件传输助手发1"))


if __name__ == "__main__":
    unittest.main()
