import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ImportBehaviorTests(unittest.TestCase):
    def test_agent_import_does_not_require_llm_token(self):
        env = os.environ.copy()
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["PYTHONPATH"] = str(ROOT / "src")

        result = subprocess.run(
            [sys.executable, "-c", "import agent; print('ok')"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
