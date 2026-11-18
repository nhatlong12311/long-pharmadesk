# -*- coding: utf-8 -*-
"""
Pharma Desk V2.9 - Bao cao phan ung co hai cua thuoc (ADR).
Dien thong tin vao MAU PDF chinh thuc (115 truong) -> PDF da dien + ban Word chinh sua duoc.
- Chu nhap vao in bang font Unicode (Liberation Sans) len dung o cua mau -> hien thi du dau tieng Viet.
- O tick/nut chon dung chinh hinh o trong mau (chon /AS cua widget).
"""
import datetime, io, json, os, re, threading, uuid
from pathlib import Path

from common import save_document, iter_sheets, atomic_write_json, file_routes, guarded, norm, safe

CFG = {"root": Path("."), "data": Path(".")}
_LOCK = threading.Lock()


def init(root, data_dir):
    CFG["root"], CFG["data"] = Path(root), Path(data_dir)
    for sub in ("Bao_cao", "Ban_nhap"):
        (CFG["data"] / sub).mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------- anh xa truong
DRUG_COLS = ["ten", "dang", "nsx", "lo", "lieu", "solan", "duong", "bd", "kt", "lydo"]
DRUG_FIELDS = [
    ["TenthuocNN1", "DangBC1", "NSX1", "fill_10", "fill_11", "tháng", "Text7", "comb_2", "Text8", "fill_12"],
    ["TenthuocNN2", "DangBC2", "fill_15", "fill_16", "fill_17", "undefined_2", "Text9", "undefined_3", "Text10", "fill_18"],
    ["TenthuocNN3", "DangBC3", "fill_21", "fill_22", "fill_23", "undefined_4", "Text11", "undefined_5", "Text12", "fill_24"],
    ["TenthuocNN4", "DangBC4", "fill_27", "fill_28", "fill_29", "fill_30", "fill_31", "fill_32", "fill_33", "fill_34"],
]
CON_FIELDS = [  # moi hang: (trai[ten,dang,bd,kt], phai[...])
    (["Tenthuoc5", "DangBC5", "fill_69", "fill_70"], ["Tenthuoc6", "DangBC6", "fill_73", "fill_74"]),
    (["Tenthuoc7", "DangBC7", "fill_77", "fill_78"], ["Tenthuoc8", "DangBC8", "fill_81", "fill_82"]),
    (["Tenthuoc9", "DangBC9", "fill_85", "fill_86"], ["Tenthuoc10", "DangBC10", "fill_89", "fill_90"]),
    (["Tenthuoc11", "DangBC11", "fill_93", "fill_94"], ["Tenthuoc12", "fill_96", "fill_97", "fill_98"]),
    (["Tenthuoc13", "fill_100", "fill_101", "fill_102"], ["Tenthuoc14", "fill_104", "fill_105", "fill_106"]),
]
Q14_GROUPS = ["Group5", "Group6", "Group9", "Group11"]
Q15_GROUPS = ["Group7", "Group8", "Group10", "Group12"]
SIMPLE = {"noi_bc": "Tendonvi", "ma_donvi": "MaBCdonvi", "ten_bn": "TenBN", "ngay_sinh": "Ngaysinh", "tuoi": "Tuoi",
          "can_nang": "Cannang", "ngay_pu": "NgayPhanUng", "thoi_gian": "ThoiGianTiemTang", "mo_ta": "MotaBieuhien",
          "xet_nghiem": "Xetnghiem", "tien_su": "Tiensu", "xu_tri": "Xutri", "q17_khac": "undefined_6",
          "q18_khac": "undefined_7", "binh_luan": "fill_21_2", "nguoi_ten": "fill_5_2", "nghe": "fill_6_2",
          "dt": "fill_7_2", "email": "Email", "chu_ky": "fill_22_2", "ngay_bc": "Text13"}
MULTI_LINE = {"MotaBieuhien", "Xetnghiem", "Tiensu", "Xutri", "fill_21_2"}


def _font_path(bold=False):
    name = "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"
    for p in (CFG["root"] / "ADR" / "fonts" / name,
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"),
              Path("/usr/share/fonts/truetype/liberation") / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        if p.exists():
            return str(p)
    raise FileNotFoundError("Không tìm thấy font Unicode (ADR\\fonts\\LiberationSans-Regular.ttf).")


def _s(v):
    return "" if v is None else str(v).strip()


# ----------------------------------------------------------------------------- PDF
def _collect(reader):
    """Ten truong -> [(page, rect)] cho o chu; nhom nut -> danh sach widget."""
    texts, groups = {}, {}
    for pi, page in enumerate(reader.pages):
        an = page.get("/Annots")
        for a in (an.get_object() if an is not None else []):
            o = a.get_object()
            if o.get("/Subtype") != "/Widget":
                continue
            par = o.get("/Parent")
            name = o.get("/T") if o.get("/T") is not None else (par.get_object().get("/T") if par is not None else None)
            ft = o.get("/FT") or (par.get_object().get("/FT") if par is not None else None)
            r = [float(x) for x in o["/Rect"]]
            rect = (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
            if ft == "/Tx":
                texts[name] = (pi, rect)
            elif ft == "/Btn":
                on = [k for k in (o["/AP"]["/N"].keys() if "/AP" in o else []) if k != "/Off"]
                groups.setdefault(name, []).append({"annot": o, "rect": rect, "on": on[0] if on else None, "page": pi,
                                                    "parent": par.get_object() if par is not None else None})
    return texts, groups


def _wrap(text, font, size, width):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines = []
    for para in text.replace("\r", "").split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            t = (cur + " " + w).strip() if cur else w
            if stringWidth(t, font, size) <= width:
                cur = t
                continue
            if cur:
                lines.append(cur)
            # tu qua dai -> cat theo ky tu
            while stringWidth(w, font, size) > width and len(w) > 1:
                k = len(w)
                while k > 1 and stringWidth(w[:k], font, size) > width:
                    k -= 1
                lines.append(w[:k])
                w = w[k:]
            cur = w
        lines.append(cur)
    return lines


def _fit(text, rect, font, smax, smin, multiline):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    x0, y0, x1, y1 = rect
    w, h = x1 - x0 - 3.0, y1 - y0 - 1.5
    size = smax
    while size >= smin - 1e-6:
        words_ok = all(stringWidth(t, font, size) <= w for t in re.split(r"\s+", text) if t)
        lines = _wrap(text, font, size, w)
        if words_ok and len(lines) * size * 1.12 <= h + 0.01:
            return size, lines, False
        size -= 0.25
    size = smin
    lines = _wrap(text, font, size, w)
    cap = max(1, int(h // (size * 1.12)))
    return size, lines[:cap], len(lines) > cap


def fill_pdf(data, out_path, template=None):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, NumberObject
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    template = template or (CFG["root"] / "ADR" / "Mau_bao_cao_ADR.pdf")
    if not Path(template).exists():
        raise FileNotFoundError(f"Không thấy mẫu PDF: {template}")
    if "AdrSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("AdrSans", _font_path()))
    writer = PdfWriter(clone_from=str(template))
    texts, groups = _collect(writer)
    warnings = []

    # ---- gom van ban can in
    items = {}  # ten truong -> noi dung
    for k, f in SIMPLE.items():
        if _s(data.get(k)):
            items[f] = _s(data[k])
    for r, d in enumerate((data.get("thuoc") or [])[:4]):
        for c, f in zip(DRUG_COLS, DRUG_FIELDS[r]):
            if _s(d.get(c)):
                items[f] = _s(d[c])
    for i, d in enumerate((data.get("con") or [])[:10]):
        row, side = divmod(i, 2)
        for c, f in zip(("ten", "dang", "bd", "kt"), CON_FIELDS[row][side]):
            if _s(d.get(c)):
                items[f] = _s(d[c])

    # ---- in chu (overlay)
    per_page = {}
    for name, txt in items.items():
        if name not in texts:
            continue
        pi, rect = texts[name]
        per_page.setdefault(pi, []).append((name, rect, txt))
    for pi, lst in per_page.items():
        page = writer.pages[pi]
        W, H = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(W, H))
        for name, rect, txt in lst:
            x0, y0, x1, y1 = rect
            big = (y1 - y0) > 40 and name in MULTI_LINE
            cell = name in sum(DRUG_FIELDS, []) or any(name in sum([l, r], []) for l, r in CON_FIELDS)
            smax = 10 if not cell else 8.5
            smin = 5.5 if not cell else 5.0
            size, lines, cut = _fit(txt, rect, "AdrSans", smax, smin, big)
            if cut:
                warnings.append(f"Ô \"{name}\" quá dài so với mẫu, đã cắt bớt - nên ghi gọn hoặc đính kèm trang phụ.")
            lh = size * 1.12
            block = len(lines) * lh
            if big or len(lines) > 1 and (y1 - y0) > 22 and not cell:
                ytop = y1 - 1.0 - size * 0.9
            else:
                ytop = (y0 + y1) / 2 + block / 2 - size * 0.82
            c.setFont("AdrSans", size)
            c.setFillColorRGB(0.04, 0.10, 0.45)
            for j, ln in enumerate(lines):
                c.drawString(x0 + 1.8, ytop - j * lh, ln)
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])

    # ---- o tick / nut chon: thay hinh o (appearance) bang o co dau tick tu ve (khong phu thuoc ZapfDingbats)
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject
    ticks = []  # (kid)

    def choose(gname, on_names=None, index=None):
        kids = groups.get(gname) or []
        order = sorted(kids, key=lambda k: k["rect"][0])
        if index is not None and 0 <= index < len(order):
            ticks.append(order[index])
        elif on_names:
            ticks.extend(k for k in kids if k["on"] in on_names)

    if data.get("gioi") in ("M", "F"):
        choose("Gioi", ["/" + data["gioi"]])
    mu = [str(x) for x in (data.get("muc_do") or []) if str(x) in "123456"]
    if mu:
        choose("MucdoNT", ["/" + x for x in mu])
    if str(data.get("ket_qua", "")) in list("1234567"):
        choose("KetquaXT", ["/" + str(data["ket_qua"])])
    for r, d in enumerate((data.get("thuoc") or [])[:4]):
        if str(d.get("q14", "")) in list("0123"):
            choose(Q14_GROUPS[r], index=int(d["q14"]))
        if str(d.get("q15", "")) in list("0123"):
            choose(Q15_GROUPS[r], index=int(d["q15"]))
    if str(data.get("q17", "")) in list("1234567"):
        choose("Group13", ["/" + str(data["q17"])])
    if str(data.get("q18", "")) in list("123"):
        choose("Group14", ["/" + str(data["q18"])])
    if str(data.get("dang_bc", "")) in ("1", "2"):
        choose("Group15", ["/" + str(data["dang_bc"])])
    for k in ticks:
        x0, y0, x1, y1 = k["rect"]
        w, h = x1 - x0, y1 - y0
        ops = (f"q 1 g 0 0 {w:.2f} {h:.2f} re f 0 G 0.6 w 0.3 0.3 {w - 0.6:.2f} {h - 0.6:.2f} re S "
               f"0.04 0.10 0.45 RG 1.6 w 1 J 1 j {w * .16:.2f} {h * .50:.2f} m {w * .42:.2f} {h * .18:.2f} l "
               f"{w * .94:.2f} {h * .98:.2f} l S Q")
        st = DecodedStreamObject()
        st.set_data(ops.encode("latin-1"))
        st.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                   NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(w), FloatObject(h)]),
                   NameObject("/Resources"): DictionaryObject()})
        ref = writer._add_object(st)
        ap_n = k["annot"]["/AP"]["/N"]
        ap_n = ap_n.get_object() if hasattr(ap_n, "get_object") else ap_n
        ap_n[NameObject(k["on"])] = ref
        k["annot"][NameObject("/AS")] = NameObject(k["on"])
        if k["parent"] is not None:
            k["parent"][NameObject("/V")] = NameObject(k["on"])
        else:
            k["annot"][NameObject("/V")] = NameObject(k["on"])

    # ---- khoa chi doc (khong de PDF viewer chen them chu)
    for page in writer.pages:
        for a in (page.get("/Annots") or []):
            o = a.get_object()
            if o.get("/Subtype") == "/Widget":
                for obj in (o, o.get("/Parent").get_object() if o.get("/Parent") is not None else None):
                    if obj is not None:
                        obj[NameObject("/Ff")] = NumberObject(int(obj.get("/Ff", 0) or 0) | 1)
    writer.add_metadata({"/Title": "Báo cáo phản ứng có hại của thuốc (ADR)", "/Producer": "PharmaDesk V2.9"})
    with open(out_path, "wb") as fh:
        writer.write(fh)
    return warnings


# ----------------------------------------------------------------------------- Word (chinh sua duoc)
OPT = {
    "muc_do": [("1", "Tử vong"), ("3", "Nhập viện/Kéo dài thời gian nằm viện"), ("5", "Dị tật thai nhi"),
               ("2", "Đe dọa tính mạng"), ("4", "Tàn tật vĩnh viễn/nặng nề"), ("6", "Không nghiêm trọng")],
    "ket_qua": [("1", "Tử vong do ADR"), ("3", "Chưa hồi phục"), ("5", "Hồi phục có di chứng"), ("7", "Không rõ"),
                ("2", "Tử vong không liên quan đến thuốc"), ("4", "Đang hồi phục"), ("6", "Hồi phục không có di chứng")],
    "q17": [("1", "Chắc chắn"), ("4", "Không chắc chắn"), ("2", "Có khả năng"), ("5", "Chưa phân loại"), ("3", "Có thể"),
            ("6", "Không thể phân loại")],
}
ROMAN = ["i", "ii", "iii", "iv"]


def make_docx(data, out_path):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.1)
    sec.top_margin, sec.bottom_margin = Cm(0.9), Cm(0.9)
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Arial", Pt(8.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    st.paragraph_format.space_after = st.paragraph_format.space_before = Pt(0)
    BLUE = RGBColor(0x0A, 0x1A, 0x73)
    CHK = {True: "☒", False: "☐"}

    def shade(cell, fill):
        tcPr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:color"), "auto")
        sh.set(qn("w:fill"), fill)
        tcPr.append(sh)

    def put(cell, parts, size=None, align=None, valign=None):
        """parts: str hoac list[(text, kind)] kind: '' nhan, 'v' = gia tri nhap, 'b' dam, 'i' nghieng."""
        if isinstance(parts, str):
            parts = [(parts, "")]
        p = cell.paragraphs[0]
        for ex in cell.paragraphs[1:]:
            ex._p.getparent().remove(ex._p)
        if align:
            p.alignment = align
        for text, kind in parts:
            segs = text.split("\n")
            for i, sg in enumerate(segs):
                r = p.add_run(sg)
                if size:
                    r.font.size = Pt(size)
                if kind == "v":
                    r.font.color.rgb = BLUE
                if kind == "b":
                    r.bold = True
                if kind == "i":
                    r.italic = True
                if i < len(segs) - 1:
                    r.add_break()
        if valign:
            tcPr = cell._tc.get_or_add_tcPr()
            v = OxmlElement("w:vAlign")
            v.set(qn("w:val"), valign)
            tcPr.append(v)

    def table(rows, cols, widths):
        t = doc.add_table(rows=rows, cols=cols)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        for col, w in zip(t.columns, widths):
            col.width = Cm(w)
        for row in t.rows:
            for c, w in zip(row.cells, widths):
                c.width = Cm(w)
        return t

    def bar(text):
        t = table(1, 1, [19.0])
        shade(t.cell(0, 0), "000000")
        p = t.cell(0, 0).paragraphs[0]
        r = p.add_run(text)
        r.bold = True
        r.font.color.rgb = RGBColor(255, 255, 255)
        r.font.size = Pt(9)

    def v(k):
        return _s(data.get(k))

    # ---- tieu de
    t = table(1, 2, [11.2, 7.8])
    put(t.cell(0, 0), [("BÁO CÁO PHẢN ỨNG CÓ HẠI CỦA THUỐC\n", "b"), ("THÔNG TIN VỀ NGƯỜI BÁO CÁO, BỆNH NHÂN VÀ ĐƠN VỊ BÁO CÁO SẼ ĐƯỢC BẢO MẬT", "i")], align=WD_ALIGN_PARAGRAPH.CENTER)
    t.cell(0, 0).paragraphs[0].runs[0].font.size = Pt(13)
    put(t.cell(0, 1), [("Nơi báo cáo: ", ""), (v("noi_bc"), "v"), ("\nMã số báo cáo của đơn vị: ", ""), (v("ma_donvi"), "v"),
                       ("\nMã số báo cáo (do Trung tâm quốc gia quản lý): ", "")])
    pr = doc.add_paragraph()
    pr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = pr.add_run("Xin anh/chị hãy báo cáo kể cả khi không chắc chắn về sản phẩm đã gây ra phản ứng và/hoặc không có đầy đủ các thông tin")
    r.italic = True
    r.font.size = Pt(8)

    # ---- A
    bar("A. THÔNG TIN VỀ BỆNH NHÂN")
    t = table(1, 4, [8.0, 4.4, 4.0, 2.6])
    put(t.cell(0, 0), [("1. Họ và tên: ", ""), (v("ten_bn"), "v")])
    put(t.cell(0, 1), [("2. Ngày sinh: ", ""), (v("ngay_sinh"), "v"), ("\nHoặc tuổi: ", ""), (v("tuoi"), "v")])
    g = v("gioi")
    put(t.cell(0, 2), f"3. Giới tính\n{CHK[g == 'M']} Nam    {CHK[g == 'F']} Nữ")
    put(t.cell(0, 3), [("4. Cân nặng: ", ""), (v("can_nang"), "v"), (" kg", "")])

    # ---- B
    bar("B. THÔNG TIN VỀ PHẢN ỨNG CÓ HẠI (ADR)")
    t = table(5, 2, [9.0, 10.0])
    put(t.cell(0, 0), [("5. Ngày xuất hiện phản ứng: ", ""), (v("ngay_pu"), "v")])
    put(t.cell(0, 1), [("6. Phản ứng xuất hiện sau bao lâu (tính từ lần dùng cuối cùng của thuốc nghi ngờ): ", ""), (v("thoi_gian"), "v")])
    left = t.cell(1, 0).merge(t.cell(3, 0))
    put(left, [("7. Mô tả biểu hiện ADR\n", ""), (v("mo_ta"), "v")])
    put(t.cell(1, 1), [("8. Các xét nghiệm liên quan đến phản ứng\n", ""), (v("xet_nghiem"), "v")])
    put(t.cell(2, 1), [("9. Tiền sử ", ""), ("(dị ứng, thai nghén, nghiện thuốc lá, nghiện rượu, bệnh gan, bệnh thận…)\n", "i"), (v("tien_su"), "v")])
    put(t.cell(3, 1), [("10. Cách xử trí phản ứng\n", ""), (v("xu_tri"), "v")])
    for rr, h in ((1, 2.4), (2, 2.4), (3, 2.6)):
        trPr = t.rows[rr]._tr.get_or_add_trPr()
        e = OxmlElement("w:trHeight")
        e.set(qn("w:val"), str(int(h * 567)))
        e.set(qn("w:hRule"), "atLeast")
        trPr.append(e)
    mu = {str(x) for x in (data.get("muc_do") or [])}
    c = t.cell(4, 0).merge(t.cell(4, 1))
    lines = ["11. Mức độ nghiêm trọng của phản ứng"]
    o = OPT["muc_do"]
    for i in (0, 3):
        lines.append("    ".join(f"{CHK[k in mu]} {lab}" for k, lab in o[i:i + 3]))
    put(c, "\n".join(lines))
    t2 = table(1, 1, [19.0])
    kq = v("ket_qua")
    o = OPT["ket_qua"]
    put(t2.cell(0, 0), "12. Kết quả sau khi xử trí phản ứng\n" + "    ".join(f"{CHK[k == kq]} {lab}" for k, lab in o[:4]) + "\n" +
        "    ".join(f"{CHK[k == kq]} {lab}" for k, lab in o[4:]))

    # ---- C
    bar("C. THÔNG TIN VỀ THUỐC NGHI NGỜ GÂY ADR")
    w = [0.8, 3.2, 2.0, 1.9, 1.5, 1.4, 1.5, 1.4, 1.6, 1.6, 2.1]
    t = table(6, 11, w)
    heads = ["STT", "13. Thuốc (tên gốc và tên thương mại)", "Dạng bào chế, hàm lượng", "Nhà sản xuất", "Số lô", "Liều dùng một lần",
             "Số lần dùng trong ngày/tuần/tháng", "Đường dùng", None, None, "Lý do dùng thuốc"]
    for i, h in enumerate(heads):
        if h:
            a = t.cell(0, i).merge(t.cell(1, i))
            put(a, [(h, "b")], size=7.5, align=WD_ALIGN_PARAGRAPH.CENTER, valign="center")
    a = t.cell(0, 8).merge(t.cell(0, 9))
    put(a, [("Ngày điều trị (Ngày/tháng/năm)", "b")], size=7.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    put(t.cell(1, 8), [("Bắt đầu", "b")], size=7.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    put(t.cell(1, 9), [("Kết thúc", "b")], size=7.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    for r in range(2):
        for cell in t.rows[r].cells:
            shade(cell, "E7ECF2")
    drugs = (data.get("thuoc") or []) + [{}] * 4
    for r in range(4):
        d = drugs[r]
        row = t.rows[2 + r].cells
        put(row[0], ROMAN[r], size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
        for j, key in enumerate(DRUG_COLS):
            put(row[1 + j], [(_s(d.get(key)), "v")], size=7.5)
        trPr = t.rows[2 + r]._tr.get_or_add_trPr()
        e = OxmlElement("w:trHeight")
        e.set(qn("w:val"), str(int(1.1 * 567)))
        e.set(qn("w:hRule"), "atLeast")
        trPr.append(e)

    t = table(6, 9, [1.5, 1.2, 1.4, 2.6, 2.3, 1.2, 1.4, 2.7, 2.3])
    put(t.cell(0, 0).merge(t.cell(1, 0)), [("STT (ứng 13.)", "b")], size=7, align=WD_ALIGN_PARAGRAPH.CENTER)
    put(t.cell(0, 1).merge(t.cell(0, 4)), [("14. Sau khi ngừng/giảm liều của thuốc bị nghi ngờ, phản ứng có được cải thiện không?", "b")], size=7.5)
    put(t.cell(0, 5).merge(t.cell(0, 8)), [("15. Tái sử dụng thuốc bị nghi ngờ có xuất hiện lại phản ứng không?", "b")], size=7.5)
    for j, h in enumerate(["Có", "Không", "Không ngừng/giảm liều", "Không có thông tin", "Có", "Không", "Không tái sử dụng", "Không có thông tin"]):
        put(t.cell(1, 1 + j), [(h, "b")], size=7.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    for r in range(2):
        for cell in t.rows[r].cells:
            shade(cell, "E7ECF2")
    for r in range(4):
        d = drugs[r]
        row = t.rows[2 + r].cells
        put(row[0], ROMAN[r], size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
        for j in range(4):
            put(row[1 + j], CHK[_s(d.get("q14")) == str(j)], size=9, align=WD_ALIGN_PARAGRAPH.CENTER)
            put(row[5 + j], CHK[_s(d.get("q15")) == str(j)], size=9, align=WD_ALIGN_PARAGRAPH.CENTER)

    # ---- 16
    t = table(7, 8, [3.6, 2.2, 1.9, 1.8, 3.6, 2.2, 1.9, 1.8])
    put(t.cell(0, 0).merge(t.cell(0, 7)), [("16. Các thuốc dùng đồng thời ", "b"), ("(Ngoại trừ các thuốc dùng điều trị/khắc phục hậu quả của ADR)", "i")], size=8)
    for j, h in enumerate(["Tên thuốc", "Dạng bào chế, hàm lượng", "Bắt đầu", "Kết thúc"] * 2):
        put(t.cell(1, j), [(h, "b")], size=7.5, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade(t.cell(1, j), "E7ECF2")
    con = (data.get("con") or []) + [{}] * 10
    for i in range(10):
        row, side = divmod(i, 2)
        d = con[i]
        cells = t.rows[2 + row].cells[side * 4:side * 4 + 4]
        for cell, key in zip(cells, ("ten", "dang", "bd", "kt")):
            put(cell, [(_s(d.get(key)), "v")], size=7.5)

    # ---- D
    doc.add_page_break()
    bar("D. PHẦN THẨM ĐỊNH ADR CỦA ĐƠN VỊ")
    t = table(3, 1, [19.0])
    q17 = v("q17")
    o = OPT["q17"]
    put(t.cell(0, 0), "17. Đánh giá mối liên quan giữa thuốc và ADR\n" + "\n".join(
        "    ".join(f"{CHK[k == q17]} {lab}" for k, lab in o[i:i + 2]) for i in (0, 2, 4)) +
        f"\n{CHK[q17 == '7']} Khác: " + v("q17_khac"))
    q18 = v("q18")
    put(t.cell(1, 0), f"18. Đơn vị thẩm định ADR theo thang nào?\n{CHK[q18 == '1']} Thang WHO    {CHK[q18 == '2']} Thang Naranjo    {CHK[q18 == '3']} Thang khác: " + v("q18_khac"))
    put(t.cell(2, 0), [("19. Phần bình luận của cán bộ y tế (nếu có)\n", ""), (v("binh_luan"), "v")])

    # ---- E
    bar("E. THÔNG TIN VỀ NGƯỜI BÁO CÁO")
    t = table(4, 2, [9.5, 9.5])
    put(t.cell(0, 0), [("20. Họ và tên: ", ""), (v("nguoi_ten"), "v")])
    put(t.cell(0, 1), [("Nghề nghiệp/Chức vụ: ", ""), (v("nghe"), "v")])
    put(t.cell(1, 0), [("Điện thoại liên lạc: ", ""), (v("dt"), "v")])
    put(t.cell(1, 1), [("Email: ", ""), (v("email"), "v")])
    put(t.cell(2, 0).merge(t.cell(2, 1)), [("21. Chữ ký: ", ""), (v("chu_ky"), "v")])
    db = v("dang_bc")
    put(t.cell(3, 0), f"22. Dạng báo cáo:  {CHK[db == '1']} Lần đầu    {CHK[db == '2']} Bổ sung")
    put(t.cell(3, 1), [("23. Ngày báo cáo: ", ""), (v("ngay_bc"), "v")])
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Xin chân thành cảm ơn!")
    r.bold = True
    doc.core_properties.title = "Báo cáo phản ứng có hại của thuốc (ADR)"
    save_document(doc,out_path)


# ----------------------------------------------------------------------------- tien ich + Flask
def slug(s):
    return norm(_s(s)).replace(" ", "_")[:40]


DEFAULT_KEYS = ["noi_bc", "ma_donvi", "nguoi_ten", "nghe", "dt", "email", "chu_ky"]


def load_defaults():
    p = CFG["data"] / "adr_defaults.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def generate(data):
    if not any(_s(data.get(k)) for k in ("ten_bn", "mo_ta", "ngay_pu")):
        raise ValueError("Chưa nhập thông tin phản ứng: hãy nhập ít nhất họ tên bệnh nhân hoặc mô tả biểu hiện ADR.")
    atomic_write_json(CFG["data"] / "adr_defaults.json", {k: _s(data.get(k)) for k in DEFAULT_KEYS})
    base = f"ADR_{slug(data.get('ten_bn')) or 'chua_dat_ten'}_{datetime.datetime.now():%Y%m%d_%H%M%S_%f}_{uuid.uuid4().hex[:8]}"
    outdir = CFG["data"] / "Bao_cao"
    warnings = fill_pdf(data, outdir / (base + ".pdf"))
    make_docx(data, outdir / (base + ".docx"))
    if not _s(data.get("ten_bn")):
        warnings.append("Chưa nhập họ tên bệnh nhân.")
    if not (_s(data.get("ngay_sinh")) or _s(data.get("tuoi"))):
        warnings.append("Chưa nhập ngày sinh hoặc tuổi (mẫu ADR yêu cầu ít nhất một trong hai).")
    if not [d for d in (data.get("thuoc") or []) if _s(d.get("ten"))]:
        warnings.append("Chưa nhập thuốc nghi ngờ gây ADR (mục 13).")
    return {"pdf": base + ".pdf", "docx": base + ".docx", "warnings": warnings}


def make_blueprint():
    from flask import Blueprint, jsonify, request
    bp = Blueprint("adr", __name__)
    file_routes(bp, "adr", lambda: CFG["data"] / "Bao_cao", (".pdf", ".docx"))

    @bp.get("/api/adr/state")
    def state():
        try:
            _font_path()
            font_ok = True
        except Exception:
            font_ok = False
        return jsonify(defaults=load_defaults(), template=(CFG["root"] / "ADR" / "Mau_bao_cao_ADR.pdf").exists(),
                       font=font_ok, today=datetime.date.today().strftime("%d/%m/%Y"))

    @bp.post("/api/adr/generate")
    @guarded(_LOCK, ("pypdf", "reportlab", "PIL", "docx"), perm="Không ghi được file. Nếu đang mở báo cáo cũ trong PDF/Word thì hãy đóng lại.")
    def gen():
        result = generate(request.get_json(silent=True) or {})
        # On ephemeral/cloud hosting, reports can disappear before the next GET.
        # Return the newly generated files with this response so the browser can
        # download them without depending on a shared server filesystem.
        if os.environ.get("PHARMADESK_ONLINE") == "1":
            import base64
            report_dir = CFG["data"] / "Bao_cao"
            result["inline_files"] = {}
            for key in ("pdf", "docx"):
                file_path = report_dir / result[key]
                result["inline_files"][key] = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return jsonify(ok=True, **result)

    def draft_path(name):
        # Accept legacy ASCII slugs as well as UUIDs without truncating identifiers.
        if not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,96}',name):
            raise ValueError('Mã bản nháp không hợp lệ.')
        return CFG["data"] / "Ban_nhap" / (name + ".json")

    @bp.get("/api/adr/drafts")
    def drafts():
        out = []
        for p in sorted((CFG["data"] / "Ban_nhap").glob("*.json"), key=lambda x: -x.stat().st_mtime):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"name": p.stem, "ten_bn": _s(d.get("ten_bn")),
                        "saved": datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M")})
        return jsonify(drafts=out)

    @bp.post("/api/adr/draft")
    @guarded(_LOCK)
    def draft_save():
        d = request.get_json(silent=True) or {}
        data = d.get("data") or {}
        if not isinstance(data,dict):
            raise ValueError('Dữ liệu bản nháp phải là một đối tượng.')
        name = d.get("name") or uuid.uuid4().hex
        atomic_write_json(draft_path(name), data)
        return jsonify(ok=True, name=name)

    @bp.get("/api/adr/draft")
    @safe
    def draft_load():
        p = draft_path(request.args.get("name"))
        if not p.exists():
            return jsonify(ok=False, msg="Không thấy bản nháp.")
        return jsonify(ok=True, data=json.loads(p.read_text(encoding="utf-8")))

    @bp.post("/api/adr/draft/delete")
    @guarded(_LOCK)
    def draft_del():
        draft_path((request.get_json(silent=True) or {}).get("name")).unlink(missing_ok=True)
        return jsonify(ok=True)

    return bp
