"""Regression: the deployed PharmaDesk artifact must include PharmaCount."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PharmaCountPublishTest(unittest.TestCase):
    def test_publish_static_app_without_migrations_or_private_docs(self):
        spec = importlib.util.spec_from_file_location("pharmadesk_build", ROOT / "web" / "build.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            module.copy_pharmacount(dist)
            app = dist / "pharmacount"
            self.assertTrue((app / "index.html").is_file())
            self.assertTrue((app / "pack-worker.js").is_file())
            self.assertIn("PharmaCount", (app / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(p.name for p in app.iterdir()),
                ["index.html", "pack-worker.js", "theme.css"],
                "Deployment must not expose SQL migrations, test data or source notes",
            )

    def test_build_paths_both_publish_pharmacount(self):
        src = (ROOT / "web" / "build.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(src.count("copy_pharmacount(output)"), 3)


if __name__ == "__main__":
    unittest.main()
