"""Synthetic online ADR integration tests: no real patient data, no Render secrets."""
import base64
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from docx import Document
from pypdf import PdfReader

USERNAME = "clinical"
PASSWORD = "synthetic-adr-test-password"
AUTH = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode("ascii")).decode("ascii")


class ADROnlineIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        user_data = cls.enterClassContext(tempfile.TemporaryDirectory(prefix="pharmadesk_adr_ci_"))
        cls.enterClassContext(patch.dict(os.environ, {
            "LOCALAPPDATA": user_data,
            "PHARMADESK_ONLINE": "1",
            "PHARMADESK_TOOLS_ONLY": "1",
            "PHARMADESK_USERNAME": USERNAME,
            "PHARMADESK_PASSWORD": PASSWORD,
        }))
        # The desktop tests import their own copy of the application.
        modules = {name: sys.modules.pop(name, None)
                   for name in ("app", "abcven", "adr", "common", "tdm", "ttt")}
        try:
            import app
            import adr
        finally:
            for name, module in modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        cls.adr = adr
        app.app.config["TESTING"] = True
        cls.client = app.app.test_client()
        cls.headers = {
            "Authorization": AUTH,
            "X-PharmaDesk-Token": app.SESSION_TOKEN,
        }

    def test_01_protected_and_public_routes(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        root = self.client.get("/")
        self.assertEqual(root.status_code, 302)
        self.assertEqual(root.location, "/tools?module=abc")
        blocked = self.client.post("/api/adr/generate", json={"mo_ta": "Thử"})
        self.assertEqual(blocked.status_code, 401)
        self.assertFalse(blocked.get_json()["ok"])
        self.assertEqual(blocked.headers["Cache-Control"], "no-store")
        challenge = self.client.get("/tools?module=adr")
        self.assertEqual(challenge.status_code, 401)
        self.assertTrue(challenge.headers["WWW-Authenticate"].startswith("Basic "))
        self.assertEqual(blocked.headers["WWW-Authenticate"], challenge.headers["WWW-Authenticate"])
        self.assertEqual(self.client.get("/api/adr/state", headers=self.headers).status_code, 200)
        page = self.client.get("/tools?module=adr", headers=self.headers)
        self.assertEqual(page.status_code, 200)
        self.assertIn(self.headers["X-PharmaDesk-Token"].encode(), page.data)
        self.assertNotIn(b"Personal Portfolio", page.data)
        self.assertEqual(page.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_02_adr_requires_request_token(self):
        res = self.client.post("/api/adr/generate", headers={"Authorization": AUTH}, json={"mo_ta": "Thử"})
        self.assertEqual(res.status_code, 403)
        self.assertFalse(res.get_json()["ok"])

    def test_03_official_pdf_and_word_are_returned_inline(self):
        report_dir = self.adr.CFG["data"] / "Bao_cao"
        before = set(report_dir.iterdir()) if report_dir.exists() else set()
        test_data = {
            "ten_bn": "MẪU THỬ ADR",
            "tuoi": "45",
            "gioi": "F",
            "mo_ta": "Phản ứng trong ca kiểm thử giả lập.",
            "thuoc": [{"ten": "THUỐC KIỂM THỬ", "lieu": "1 viên", "q14": "0"}],
            "noi_bc": "Đơn vị kiểm thử",
            "nguoi_ten": "Người kiểm thử",
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
        pdf = PdfReader(io.BytesIO(pdf_bytes))
        template = PdfReader(self.adr.CFG["root"] / "ADR" / "Mau_bao_cao_ADR.pdf")
        self.assertEqual([tuple(p.mediabox) for p in pdf.pages],
                         [tuple(p.mediabox) for p in template.pages])
        fields = pdf.get_fields()
        self.assertEqual(len(fields), 115)
        self.assertEqual(fields.keys(), template.get_fields().keys())
        self.assertEqual(fields["Gioi"]["/V"], "/F")
        self.assertIn(test_data["ten_bn"], pdf.pages[0].extract_text())
        self.assertIn(test_data["mo_ta"], pdf.pages[0].extract_text())
        doc = Document(io.BytesIO(word_bytes))
        doc_text = " ".join(cell.text for tbl in doc.tables for row in tbl.rows for cell in row.cells)
        self.assertIn(test_data["ten_bn"], doc_text)
        self.assertIn(test_data["thuoc"][0]["ten"], doc_text)
        after = set(report_dir.iterdir()) if report_dir.exists() else set()
        self.assertEqual(after, before, "Online ADR must not retain generated reports on disk")
        self.assertFalse((self.adr.CFG["data"] / "adr_defaults.json").exists())
        download = self.client.get("/api/adr/download", headers=self.headers,
                                   query_string={"name": payload["pdf"]})
        self.assertEqual(download.status_code, 404)

    def test_04_adr_bad_input_is_json_not_html(self):
        response = self.client.post("/api/adr/generate", headers=self.headers, json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.mimetype, "application/json")
        self.assertFalse(response.get_json()["ok"])

    def test_long_unbroken_text_is_clipped_in_pdf_and_preserved_in_word(self):
        text = "X" * 8192
        response = self.client.post("/api/adr/generate", headers=self.headers,
                                    json={"mo_ta": text})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(any("MotaBieuhien" in warning for warning in payload["warnings"]))
        word_bytes = base64.b64decode(payload["inline_files"]["docx"], validate=True)
        document = Document(io.BytesIO(word_bytes))
        self.assertTrue(any(text in cell.text for table in document.tables
                            for row in table.rows for cell in row.cells))


if __name__ == "__main__":
    unittest.main()
