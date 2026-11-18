"""HTTP smoke tests for online PharmaDesk: all inputs synthetic.

This suite intentionally keeps clinical calculations untouched.
Run against an isolated copy and synthetic credentials; no real patient data.
"""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from docx import Document
from pypdf import PdfReader

ORIGINAL = Path(__file__).resolve().parents[1]


def excel_bytes(rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


class CompletePharmaDeskSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="pharmadesk_all_smoke_")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name) / "application"
        shutil.copytree(ORIGINAL, cls.root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        sys.path.insert(0, str(cls.root))
        cls.addClassCleanup(sys.path.remove, str(cls.root))
        cls.enterClassContext(patch.dict(os.environ, {
            "LOCALAPPDATA": str(Path(cls.temp.name) / "user"),
            "PHARMADESK_ONLINE": "1",
            "PHARMADESK_TOOLS_ONLY": "1",
            "PHARMADESK_USERNAME": "reviewer",
            "PHARMADESK_PASSWORD": "SYNTHETIC-TEST-ONLY-long-password-2026",
        }))
        modules = {name: sys.modules.pop(name, None)
                   for name in ("app", "abcven", "adr", "common", "rpt_test", "tdm", "ttt")}
        try:
            import app
            import ttt
        finally:
            for name, module in modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        cls.appmod = app
        cls.ttt = ttt
        cls.app = app.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        credential = base64.b64encode(b"reviewer:SYNTHETIC-TEST-ONLY-long-password-2026").decode()
        cls.headers = {"Authorization": "Basic " + credential,
                       "X-PharmaDesk-Token": app.SESSION_TOKEN}

    @staticmethod
    def drug_xlsx():
        return excel_bytes([
            ["Mã dược","Tên thuốc","Hoạt chất","Hàm lượng","Quy cách","VEN","ĐVT","Đơn giá","Số lượng","Thành tiền"],
            ["SYN01","Synthetic A","Substance A","10mg","Hộp 10","V","Viên",100,10,1000],
            ["SYN02","Synthetic B","Substance B","10mg","Hộp 20","E","Viên",50,4,200],
            ["SYN03","Synthetic A","Substance A","10mg","Hộp 20","V","Viên",150,2,300],
        ])

    @staticmethod
    def prescription_xlsx():
        return excel_bytes([
            ["MaBN","NgayChiDinh","MaHoatChat","Tên thuốc","Tên khoa"],
            ["SYN-PATIENT-1","18/11/2026","SYN01","Synthetic A","Review"],
            ["SYN-PATIENT-1","18/11/2026","SYN02","Synthetic B","Review"]
        ])

    def post(self, route, **kwargs):
        return self.client.post(route, headers=dict(self.headers), **kwargs)

    def test_01_public_health_private_tools_and_no_portfolio(self):
        h=self.client.get("/api/health")
        self.assertEqual(h.status_code,200)
        self.assertTrue(h.json["online"])
        self.assertEqual(self.client.get("/").status_code,302)
        self.assertTrue(self.client.get("/").headers["Location"].endswith("/tools?module=abc"))
        self.assertEqual(self.client.get("/api/adr/state").status_code,401)
        self.assertEqual(self.client.get("/tools").status_code,401)
        html=self.client.get("/tools",headers=self.headers)
        self.assertEqual(html.status_code,200)
        self.assertNotIn(b"Personal Portfolio",html.data)
        self.assertIn(self.appmod.SESSION_TOKEN.encode(),html.data)
        self.assertIn(b"PHARMADESK",html.data)

    def test_02_windows_only_actions_blocked_online(self):
        for route in ("/api/quit","/api/open","/api/clear-rpt","/api/select-folder","/api/refresh-folder","/api/ttt/open-kb"):
            with self.subTest(route=route):
                self.assertEqual(self.post(route,json={}).status_code,404)

    def test_03_abc_state_inspect_download_xlsx(self):
        state=self.client.get("/api/abc/state",headers=self.headers)
        self.assertEqual(state.status_code,200)
        self.assertTrue(state.json["template"])
        r=self.post("/api/abc/inspect",data={"file":(self.drug_xlsx(),"synthetic.xlsx")})
        self.assertEqual(r.status_code,200,r.data[:300])
        self.assertTrue(r.json["ok"],r.json)
        self.assertEqual(r.json["rows"],3)
        r=self.post("/api/abc/export-month",data={
            "opts":json.dumps({"month":11,"year":2026,"mode":"calc","a":78,"b":95}),
            "cur":(self.drug_xlsx(),"synthetic.xlsx"),
        })
        self.assertEqual(r.status_code,200,r.data[:350])
        self.assertTrue(r.json["ok"],r.json)
        out=self.client.get("/api/abc/download",query_string={"name":r.json["name"]},headers=self.headers)
        self.assertEqual(out.status_code,200)
        self.assertTrue(out.data.startswith(b"PK"))

    def test_04_abc_word_and_packaging(self):
        r=self.post("/api/abc/generate",data={
            "opts":json.dumps({"month":11,"year":2026,"mode":"calc","a":78,"b":95}),
            "cur":(self.drug_xlsx(),"synthetic.xlsx"),
        })
        self.assertEqual(r.status_code,200,r.data[:350])
        self.assertTrue(r.json["ok"],r.json)
        out=self.client.get("/api/abc/download",query_string={"name":r.json["name"]},headers=self.headers)
        self.assertEqual(out.status_code,200)
        self.assertTrue(out.data.startswith(b"PK"))

    def test_05_drug_interactions_state_inspect_word(self):
        state=self.client.get("/api/ttt/state",headers=self.headers)
        self.assertEqual(state.status_code,200)
        self.assertTrue(state.json["template"])
        self.assertGreater(state.json["rules"].get("pairs",0),0)
        r=self.post("/api/ttt/inspect",data={"file":(self.prescription_xlsx(),"prescription.xlsx")})
        self.assertEqual(r.status_code,200,r.data[:350])
        self.assertTrue(r.json["ok"],r.json)
        self.assertEqual(r.json["rows"],2)
        r=self.post("/api/ttt/generate",data={
            "opts":json.dumps({"month":11,"year":2026,"by_name":False,"dmy":True}),
            "file":(self.prescription_xlsx(),"prescription.xlsx"),
        })
        self.assertEqual(r.status_code,200,r.data[:350])
        self.assertTrue(r.json["ok"],r.json)
        doc=self.client.get("/api/ttt/download",query_string={"name":r.json["name"]},headers=self.headers)
        self.assertEqual(doc.status_code,200)
        Document(io.BytesIO(doc.data))

    def test_06_tdm_vancomycin_empiric(self):
        r=self.post("/api/tdm/vanco/empiric",json={"age":60,"weight":70,"height":170,"scr":1})
        self.assertEqual(r.status_code,200,r.data[:300])
        self.assertTrue(r.json["ok"],r.json)
        self.assertGreater(r.json["with_ld"]["auc0_24"],0)

    def test_07_tdm_amg_start(self):
        r=self.post("/api/tdm/amg/start",json={"age":60,"weight":70,"height":170,"scr":100,"dose":320,"tau":24})
        self.assertEqual(r.status_code,200,r.data[:350])
        self.assertTrue(r.json["ok"],r.json)
        self.assertIn("gentamicin",r.json["drugs"])
        self.assertIn("amikacin",r.json["drugs"])

    def test_08_tdm_two_concentration_validation(self):
        # Invalid samples must fail consistently: no fabricated dose recommendation.
        for route in ("/api/tdm/vanco/two","/api/tdm/amg/two"):
            with self.subTest(route=route):
                r=self.post(route,json={})
                self.assertFalse(r.json["ok"],r.json)
                self.assertEqual(r.mimetype,"application/json")

    def test_09_adr_original_pdf_and_docx(self):
        state=self.client.get("/api/adr/state",headers=self.headers)
        self.assertEqual(state.status_code,200)
        self.assertTrue(state.json["template"])
        self.assertTrue(state.json["font"])
        data={"ten_bn":"BENH NHAN GIA LAP","tuoi":"45","mo_ta":"Phan ung kiem thu",
              "thuoc":[{"ten":"Thuoc gia lap","lieu":"1 vien"}]}
        r=self.post("/api/adr/generate",json=data)
        self.assertEqual(r.status_code,200,r.data[:350])
        self.assertTrue(r.json["ok"],r.json)
        if r.json.get("inline_files"):
            pdf=base64.b64decode(r.json["inline_files"]["pdf"],validate=True)
            word=base64.b64decode(r.json["inline_files"]["docx"],validate=True)
        else:
            pdf=self.client.get("/api/adr/download",query_string={"name":r.json["pdf"]},headers=self.headers).data
            word=self.client.get("/api/adr/download",query_string={"name":r.json["docx"]},headers=self.headers).data
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(PdfReader(io.BytesIO(pdf)).pages),0)
        Document(io.BytesIO(word))

    def test_10_adr_draft_roundtrip_and_delete(self):
        data={"data":{"ten_bn":"ONLY SYNTHETIC","mo_ta":"Not a real patient"}}
        r=self.post("/api/adr/draft",json=data)
        self.assertEqual(r.status_code,200,r.data[:300])
        self.assertTrue(r.json["ok"])
        name=r.json["name"]
        fetched=self.client.get("/api/adr/draft",query_string={"name":name},headers=self.headers)
        self.assertEqual(fetched.json["data"],data["data"])
        deleted=self.post("/api/adr/draft/delete",json={"name":name})
        self.assertTrue(deleted.json["ok"])

    def test_11_authentication_and_invalid_input(self):
        self.assertEqual(self.client.post("/api/adr/generate",json={}).status_code,401)
        bad=self.client.post("/api/adr/generate",headers={"Authorization":self.headers["Authorization"]},json={})
        self.assertEqual(bad.status_code,403)
        with_token=self.post("/api/adr/generate",json={})
        self.assertEqual(with_token.mimetype,"application/json")
        self.assertFalse(with_token.json["ok"])

    def test_12_tdm_valid_two_concentration_models(self):
        vanco={"dose1":1000,"tinf1":1,"tau":12,"weight":70,
               "t1":1,"t2":6,"c1":25,"c2":10}
        result=self.post("/api/tdm/vanco/two",json=vanco)
        self.assertEqual(result.status_code,200,result.data[:350])
        self.assertTrue(result.json["ok"],result.json)
        self.assertGreater(result.json["pk"]["cl"],0)
        amg={"dose":320,"tau":24,"tinf":0.5,"t1":1,"t2":8,"c1":14,"c2":3}
        result=self.post("/api/tdm/amg/two",json=amg)
        self.assertEqual(result.status_code,200,result.data[:350])
        self.assertTrue(result.json["ok"],result.json)
        self.assertGreater(result.json["pk"]["cl"],0)

    def test_13_abc_month_comparison_and_packaging(self):
        previous=excel_bytes([
            ["Mã dược","Tên thuốc","Hoạt chất","Hàm lượng","Quy cách","VEN","ĐVT","Đơn giá","Số lượng","Thành tiền"],
            ["SYN01","Synthetic A","Substance A","10mg","Hộp 10","V","Viên",100,9,900],
            ["SYN03","Synthetic A","Substance A","10mg","Hộp 20","V","Viên",150,1,150],
        ])
        result=self.post("/api/abc/compare-month",data={
            "opts":json.dumps({"month":11,"year":2026,"mode":"calc","a":78,"b":95}),
            "prev":(previous,"synthetic_prev.xlsx"),
            "cur":(self.drug_xlsx(),"synthetic_current.xlsx"),
        })
        self.assertEqual(result.status_code,200,result.data[:300])
        self.assertTrue(result.json["ok"],result.json)
        report=self.client.get("/api/abc/download",query_string={"name":result.json["name"]},headers=self.headers)
        self.assertEqual(report.status_code,200)
        self.assertTrue(report.data.startswith(b"PK"))

    def test_14_interaction_detection_from_bundled_original_rules(self):
        # Use actual rule IDs/codes, but only a synthetic encounter and date.
        rules=self.ttt.load_rules()
        pair=next((a,b) for a,b in rules["pairs"]
                  if rules["drugs"][a].get("codes") and rules["drugs"][b].get("codes"))
        a,b=pair
        code_a=rules["drugs"][a]["codes"][0]
        code_b=rules["drugs"][b]["codes"][0]
        wb=excel_bytes([
            ["MaBN","NgayChiDinh","MaHoatChat","Tên thuốc","Tên khoa"],
            ["SYN-NO-PATIENT","18/11/2026",code_a,rules["drugs"][a]["ten"],"Review"],
            ["SYN-NO-PATIENT","18/11/2026",code_b,rules["drugs"][b]["ten"],"Review"],
        ])
        res=self.post("/api/ttt/inspect",data={"dmy":"1","file":(wb,"rule_check.xlsx")})
        self.assertEqual(res.status_code,200,res.data[:450])
        self.assertTrue(res.json["ok"],res.json)
        self.assertGreaterEqual(res.json["matched"],2,res.json)
        self.assertGreaterEqual(res.json["events"],1,res.json)

    def test_15_subtract_total_is_available_only_in_local_app(self):
        response = self.post("/api/test/compare")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.is_json)

    def test_16_original_windows_dependencies_present(self):
        missing=[p for p in ("Gop_va_sort_AZ.py", "Xuat_RPT_sang_XLS.vbs", "rpt_test.py", "Mau tong.xlsx")
                 if not (self.root/p).exists()]
        self.assertFalse(missing,"Original merge/RPT assets missing from GitHub: "+", ".join(missing))


if __name__=="__main__":
    unittest.main()
