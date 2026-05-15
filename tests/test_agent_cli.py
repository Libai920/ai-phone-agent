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

    def test_send_task_without_yes_only_previews(self):
        result = subprocess.run(
            [sys.executable, "src/agent.py", "给微信文件传输助手发1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "confirmation_required")
        self.assertEqual(payload["intent"]["type"], "send")
        self.assertEqual(payload["intent"]["text"], "1")
        self.assertIn("--yes", payload["message"])

    def test_send_task_with_yes_runs_normally(self):
        code = (
            "import sys;"
            "sys.path.insert(0, 'src');"
            "import agent;"
            "calls=[];"
            "agent.run=lambda task: calls.append(task) or True;"
            "raise SystemExit(agent.main(['--yes', '给微信文件传输助手发1']))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
