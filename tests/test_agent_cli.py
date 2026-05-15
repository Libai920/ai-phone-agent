import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentCliTests(unittest.TestCase):
    def test_dry_run_prints_intent_without_running_phone_actions(self):
        result = subprocess.run(
            [sys.executable, "src/agent.py", "--dry-run", "给微信文件传输助手发1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task"], "给微信文件传输助手发1")
        self.assertEqual(payload["intent"], {
            "type": "send",
            "target": "微信文件传输助手",
            "text": "1",
        })


if __name__ == "__main__":
    unittest.main()
