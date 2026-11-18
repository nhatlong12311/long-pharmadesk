# -*- coding: utf-8 -*-
"""Tien ich dung chung cho cac module bao cao (ABC/VEN, tuong tac thuoc, TDM, ADR)."""
import contextlib, copy, functools, importlib.util, json, os, re, tempfile, unicodedata
from pathlib import Path


def norm(s):
    """Chu thuong, bo dau tieng Viet, chi giu chu/so (de so khop tieu de cot, ten thuoc)."""
    s = unicodedata.normalize("NFD", str(s if s is not None else "").lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ----------------------------------------------------------------------------- doc Excel
MAX_COLS = 128  # file xuat benh vien co the co dinh dang toi cot XFB (16384 cot) du chi co ~30 cot du lieu


def atomic_write_text(path, text, encoding="utf-8"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(name)


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


def save_data_workbook(wb, path):
    """Save a generated data workbook; all strings are literal user data, never formulas."""
    for sheet in wb.worksheets:
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        wb.save(name)
        os.replace(name, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(name)


def save_document(doc, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        doc.save(name)
        os.replace(name, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(name)


def read_sheets(path):
    return list(iter_sheets(path))


def iter_sheets(path, selected=None):
    """Read one sheet at a time and close the workbook even when parsing fails."""
    p = Path(path)
    if p.suffix.lower() == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(p))
        try:
            for sh in wb.sheets():
                if selected is not None and sh.name != selected:
                    continue
                rows = []
                for i in range(sh.nrows):
                    r = []
                    for j in range(min(sh.ncols, MAX_COLS)):
                        c = sh.cell(i, j)
                        if c.ctype == xlrd.XL_CELL_DATE:
                            try:
                                r.append(xlrd.xldate_as_datetime(c.value, wb.datemode))
                            except Exception:
                                r.append(None)
                        elif c.ctype in (xlrd.XL_CELL_ERROR, xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                            r.append(None)
                        else:
                            r.append(c.value)
                    rows.append(r)
                yield sh.name, rows
        finally:
            wb.release_resources()
    else:
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                if selected is not None and ws.title != selected:
                    continue
                yield ws.title, [list(r) for r in ws.iter_rows(max_col=min(ws.max_column or MAX_COLS, MAX_COLS), values_only=True)]
        finally:
            wb.close()


# ----------------------------------------------------------------------------- Flask
@contextlib.contextmanager
def upload(field, exts=(".xlsx", ".xlsm", ".xls")):
    """Luu tam file tai len (request.files[field]) -> Path (hoac None); xoa ngay sau khi dung."""
    from flask import request
    f = request.files.get(field)
    if not f or not f.filename:
        yield None
        return
    ext = Path(f.filename).suffix.lower()
    if ext not in exts:
        raise ValueError(f"File '{f.filename}' không đúng định dạng ({'/'.join(exts)}).")
    fd, name = tempfile.mkstemp(suffix=ext, prefix="pd_")
    os.close(fd)
    p = Path(name)
    try:
        f.save(p)
        yield p
    finally:
        with contextlib.suppress(OSError):
            p.unlink()


def err_json(e):
    import traceback
    from flask import jsonify
    traceback.print_exc()
    if isinstance(e, (ValueError, TypeError, KeyError)):
        return jsonify(ok=False, msg=str(e)), 400
    if isinstance(e, FileNotFoundError):
        return jsonify(ok=False, msg="Không tìm thấy file cần xử lý."), 404
    return jsonify(ok=False, msg="Không xử lý được dữ liệu. Vui lòng xem nhật ký ứng dụng."), 500


def safe(fn):
    """Bat moi loi cua endpoint -> {ok: False, msg}."""
    @functools.wraps(fn)
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            return err_json(e)
    return w


PIP = {"PIL": "Pillow", "docx": "python-docx", "pypdf": "pypdf", "reportlab": "reportlab", "openpyxl": "openpyxl", "xlrd": "xlrd"}


def guarded(lock, libs=(), busy="Đang xử lý, vui lòng chờ...",
            perm="Không ghi được file. Nếu đang mở báo cáo cũ trong Word/PDF thì hãy đóng lại rồi thử lại."):
    """Endpoint tao bao cao: chi cho 1 luot cung luc, kiem tra thu vien, dich loi ghi file."""
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **k):
            from flask import jsonify
            if not lock.acquire(blocking=False):
                return jsonify(ok=False, msg=busy), 409
            try:
                for m in libs:
                    if importlib.util.find_spec(m) is None:
                        return jsonify(ok=False, msg=f"Thiếu thư viện {PIP.get(m, m)}. Chạy Cai_dat_thu_vien.bat rồi mở lại phần mềm.")
                return fn(*a, **k)
            except PermissionError:
                return jsonify(ok=False, msg=perm), 409
            except Exception as e:
                return err_json(e)
            finally:
                lock.release()
        return w
    return deco


def file_routes(bp, prefix, folder, exts=(".docx", ".pdf")):
    """Them /api/<prefix>/download, /view (xem truc tiep), /open (mo thu muc) cho thu muc bao cao."""
    from flask import jsonify, request, send_file

    def pick():
        p = folder() / Path(request.args.get("name") or (request.get_json(silent=True) or {}).get("name", "")).name
        return p if p.exists() and p.suffix.lower() in exts else None

    @bp.get(f"/api/{prefix}/download", endpoint=f"{prefix}_dl")
    def dl():
        p = pick()
        return send_file(p, as_attachment=True, download_name=p.name) if p else (jsonify(ok=False, msg="Không thấy file."), 404)

    @bp.get(f"/api/{prefix}/view", endpoint=f"{prefix}_view")
    def view():
        p = pick()
        return send_file(p, download_name=p.name) if p else (jsonify(ok=False, msg="Không thấy file."), 404)

    @bp.post(f"/api/{prefix}/open", endpoint=f"{prefix}_open")
    def open_():
        if os.name != "nt":
            return jsonify(ok=False, msg="Chỉ mở được trên Windows. Hãy dùng nút Tải về.")
        p = pick() or folder()
        os.startfile(str(p))
        return jsonify(ok=True)


# ----------------------------------------------------------------------------- Word (python-docx)
def find_par(doc, pred):
    for p in doc.paragraphs:
        if pred(p.text.strip()):
            return p
    raise KeyError("Mẫu Word không đúng cấu trúc (thiếu đoạn văn cần điền) - hãy dùng đúng file mẫu đi kèm.")


def set_par(par, segs):
    """Ghi lai noi dung doan, giu dinh dang cua run dau tien co chu. segs: str hoac [(text, {'b': bool})]."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.text.run import Run
    if isinstance(segs, str):
        segs = [(segs, {})]
    p = par._p
    runs = p.findall(qn("w:r"))
    donor = next((r for r in runs if "".join(t.text or "" for t in r.findall(qn("w:t"))).strip()), None)
    if donor is None and runs:
        donor = runs[0]
    if donor is None:
        donor = par.add_run()._r
        ppr_rpr = p.find(qn("w:pPr") + "/" + qn("w:rPr"))
        if ppr_rpr is not None:
            donor.insert(0, copy.deepcopy(ppr_rpr))
    base = copy.deepcopy(donor)
    for ch in list(p):
        if ch.tag != qn("w:pPr"):
            p.remove(ch)
    for text, fmt in segs:
        r = copy.deepcopy(base)
        for ch in list(r):
            if ch.tag != qn("w:rPr"):
                r.remove(ch)
        if fmt.get("b") is not None:
            rpr = r.find(qn("w:rPr"))
            if rpr is None:
                rpr = OxmlElement("w:rPr")
                r.insert(0, rpr)
            for tag in ("w:b", "w:bCs"):
                for e in rpr.findall(qn(tag)):
                    rpr.remove(e)
            if fmt["b"]:
                fonts = rpr.find(qn("w:rFonts"))
                rpr.insert(list(rpr).index(fonts) + 1 if fonts is not None else 0, OxmlElement("w:b"))
        Run(r, par).text = text
        p.append(r)


def repl_group(par, pattern, value):
    """Thay noi dung nhom 1 cua regex (chu bi chia nho qua nhieu run), giu dinh dang run."""
    from docx.oxml.ns import qn
    pieces = []
    for r in par._p.findall(qn("w:r")):
        ts = r.findall(qn("w:t"))
        pieces.append((ts, "".join(t.text or "" for t in ts)))
    mt = re.search(pattern, "".join(x[1] for x in pieces))
    if not mt:
        return False
    s, e = mt.span(1)
    pos, done = 0, False
    for ts, txt in pieces:
        a, b = pos, pos + len(txt)
        pos = b
        if b <= s or a >= e or not ts:
            continue
        lo, hi = max(s, a) - a, min(e, b) - a
        ts[0].text = txt[:lo] + (value if not done else "") + txt[hi:]
        ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for t in ts[1:]:
            t.text = ""
        done = True
    return True


def set_cell(tc, parent, text):
    """Ghi van ban vao o (w:tc), giu dinh dang run dau."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    ps = tc.findall(qn("w:p"))
    for extra in ps[1:]:
        tc.remove(extra)
    set_par(Paragraph(ps[0], parent), text)


def fill_rows(tbl, rows, empty_text=None):
    """Thay cac dong du lieu (tu dong thu 2) bang ban sao cua dong mau dau tien. rows: list[list[str]]."""
    from docx.oxml.ns import qn
    trs = tbl._tbl.findall(qn("w:tr"))
    proto = copy.deepcopy(trs[1])
    for tr in trs[1:]:
        tbl._tbl.remove(tr)
    if not rows and empty_text:
        n = len(proto.findall(qn("w:tc")))
        rows = [[empty_text if i == min(1, n - 1) else "" for i in range(n)]]
    for vals in rows:
        tr = copy.deepcopy(proto)
        tbl._tbl.append(tr)
        for tc, v in zip(tr.findall(qn("w:tc")), vals):
            set_cell(tc, tbl, v)
