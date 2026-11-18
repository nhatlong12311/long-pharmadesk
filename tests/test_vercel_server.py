import subprocess
import sys
import unittest
from pathlib import Path
from textwrap import dedent


class VercelRequestIsolation(unittest.TestCase):
    def test_browser_settings_do_not_leak_between_requests(self):
        # Import the Vercel entry point in its own process, just as in deployment.
        result = subprocess.run(
            [sys.executable, "-c", dedent("""
                from api.clinical import RULES, app

                rules = {
                    "drugs": {
                        "a": {"ten": "Mẫu A", "codes": ["SYN-A"]},
                        "b": {"ten": "Mẫu B", "codes": ["SYN-B"]},
                    },
                    "pairs": [["a", "b"]],
                }
                with app.test_client() as client:
                    custom = client.post("/api/clinical?_clinical_path=ttt/state",
                                         json={"_state": {RULES: rules}})
                    assert custom.status_code == 200, custom.get_json()
                    assert custom.json["rules"]["pairs"] == 1
                    defaults = client.get("/api/ttt/state")
                    assert defaults.status_code == 200, defaults.get_json()
                    assert defaults.json["rules"]["pairs"] > 300
                    assert defaults.headers["Cache-Control"] == "private, no-store"
            """)],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
