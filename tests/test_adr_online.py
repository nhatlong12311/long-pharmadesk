"""Synthetic online ADR integration tests: no real patient data, no Render secrets."""
import base64
import io
import os
from pathlib import Path
import tempfile
import unittest

from docx import Document
from pypdf import PdfReader

# Import app with a disposable user-data directory and synthetic CI credentials.
_TEST_DIR = tempfile.TemporaryDirectory(prefix="pharmadesk_adr_ci_")
os.environ["LOCALAPPDATA"] = _TEST_DIR.name
os.environ["PHARMADESK_ONLINE"] = "1"
os.environ["PHARMADESK_USERNAME"] = "clinical"
os.environ["PHARMADESK_PASSWORD"] = "CI-Only-Synthetic-Password-2026-Secure!"

import app  # noqa: E402
import adr  # noqa: E402

AUTH = "Basic " + base64.b64encode(
    b"clinical:CI-Only-Synthetic-Password-2026-Secure!"
).decode("ascii")


class ADROnlineIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.client = app.app.test_client()
        cls.headers = {
            "Authorization": AUTH,
            "X-PharmaDesk-Token": app.SESSION_TOKEN,
        }

    @classmethod
    def tearDownClass(cls):
        _TEST_DIR.cleanup()

    def test_01_protected_and_public_routes(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/adr/state").status_code, 401)
        self.assertEqual(self.client.get("/tools?module=adr").status_code, 401)
        self.assertEqual(self.client.get("/api/adr/state", headers=self.headers).status_code, 200)
        page = self.client.get("/tools?module=adr", headers=self.headers)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"__PHARMADESK_TOKEN__", page.data.replace(app.SESSION_TOKEN.encode(), b"__PHARMADESK_TOKEN__"))
        self.assertEqual(page.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_02_adr_requires_request_token(self):
        res = self.client.post("/api/adr/generate", headers={"Authorization": AUTH}, json={"mo_ta": "Thử"})
        self.assertEqual(res.status_code, 403)

    def test_03_official_pdf_and_word_are_returned_inline(self):
        report_dir = adr.CFG["data"] / "Bao_cao"
        before = set(report_dir.iterdir()) if report_dir.exists() else set()
        test_data = {
            "ten_bn": "BENH NHAN GIA LAP KHONG CO THAT",
            "tuoi": "45",
            "mo_ta": "Noi ban do trong ca kiem thu gia lap.",
            "thuoc": [{"ten": "THUOC KIEM THU", "lieu": "1 vien"}],
            "noi_bc": "Don vi kiem thu",
            "nguoi_ten": "Nguoi kiem thu",
        }
        response = self.client.post("/api/adr/generate", headers=self.headers, json=test_data)
        self.assertEqual(response.status_code, 200, response.data[:350])
        self.assertEqual(response.mimetype, "application/json")
        payload = response.get_json()
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["pdf"].endswith(".pdf"))
        self.assertTrue(payload["docx"].endswith(".docx"))
        pdf_bytes = base64.b64decode(payload["inline_files"]["pdf"], validate=True)
        word_bytes = base64.b64decode(payload["inline_files"]["docx"], validate=True)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertTrue(word_bytes.startswith(b"PK"))
        self.assertGreater(len(PdfReader(io.BytesIO(pdf_bytes)).pages), 0)
        doc = Document(io.BytesIO(word_bytes))
        doc_text = " ".join(cell.text for tbl in doc.tables for row in tbl.rows for cell in row.cells)
        self.assertIn("BENH NHAN GIA LAP", doc_text.upper())
        after = set(report_dir.iterdir()) if report_dir.exists() else set()
        self.assertEqual(after, before, "Online ADR must not retain generated reports on disk")
        self.assertFalse((adr.CFG["data"] / "adr_defaults.json").exists())

    def test_04_adr_bad_input_is_json_not_html(self):
        response = self.client.post("/api/adr/generate", headers=self.headers, json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.mimetype, "application/json")
        self.assertFalse(response.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
