# -*- coding: utf-8 -*-
"""
Pharma Desk V2.9.2 - Nhap mau xuat phan mem va gan ma hoat chat (xls -> word).
Chuyen doan SQL (CTE theo hoat chat + cap 'cung MaBN, cung ngay chi dinh') thanh quy tac trong Python:
  * moi hoat chat = danh sach ma hoat chat (mahoatchat) hoac ten;
  * moi cap = 2 hoat chat cung xuat hien trong cung MaBN + cung ngay chi dinh (o 2 dong thuoc khac nhau).
Dau vao: file .xls/.xlsx (sheet tuongtacthuoc, da co cot mahoatchat). Dau ra: file Word theo mau don vi.
"""
import datetime, functools, hashlib, json, os, re, shutil, threading
from collections import OrderedDict, defaultdict
from pathlib import Path

from common import save_document, iter_sheets, atomic_write_json, atomic_write_text, file_routes, fill_rows, find_par, guarded, norm, read_sheets, repl_group, safe, upload

CFG = {"root": Path("."), "data": Path(".")}
_LOCK = threading.Lock()
_BUNDLE_LOCK = threading.RLock()


def _sync_bundled(filename):
    """Install each shipped data revision once; preserve later local edits and backups."""
    source = CFG["root"] / "TUONG_TAC" / filename
    target = CFG["data"] / filename
    marker = CFG["data"] / (filename + ".bundle.sha256")
    with _BUNDLE_LOCK:
        if not source.exists():
            return target
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        previous = marker.read_text(encoding="ascii").strip() if marker.exists() else ""
        if not target.exists() or previous != digest:
            CFG["data"].mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != source.read_bytes():
                backup = CFG["data"] / "Sao_luu_truoc_cap_nhat"
                backup.mkdir(exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                shutil.copy2(target, backup / (stamp + "_" + filename))
            if source.resolve() != target.resolve():
                tmp = target.with_name(target.name + ".new")
                shutil.copy2(source, tmp)
                os.replace(tmp, target)
            atomic_write_text(marker, digest, encoding="ascii")
    return target


def init(root, data_dir, *, kb_json=None):
    CFG["root"], CFG["data"] = Path(root), Path(data_dir)
    CFG["kb_json"] = kb_json
    (CFG["data"] / "Bao_cao").mkdir(parents=True, exist_ok=True)


def _code(v):
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


# ----------------------------------------------------------------------------- quy tac tu SQL
NAME_OVERRIDE = {"levodopa_carbidopa_entacapon": "Levodopa/Carbidopa"}


def pretty(drug_id):
    return NAME_OVERRIDE.get(drug_id) or drug_id.replace("_", " ").capitalize()


def parse_sql(text):
    """Doc file SQL (WITH ... AS (...)) -> {'drugs','pairs','warnings'}."""
    t = text.replace("\r\n", "\n").lstrip("\ufeff")
    t = re.sub(r"^\s*with\s+", "", t, flags=re.I)
    ctes = {}
    for m in re.finditer(r"(?m)^(\w+) as \(\n", t):
        s = m.end()
        e = t.find("\n)", s)
        ctes[m.group(1)] = t[s:e if e >= 0 else len(t)]
    drugs, pair_def, warnings = OrderedDict(), {}, []
    for name, body in ctes.items():
        m = re.match(r"\s*SELECT \* FROM tuongtacthuoc\s*\nWHERE mahoatchat in \((.*)\)\s*$", body, re.I | re.S)
        if m:
            drugs[name] = {"ten": pretty(name), "codes": re.findall(r"'([^']*)'", m.group(1))}
            continue
        refs = re.findall(r"SELECT \* from (\w+)\s*\nwhere", body, re.I)
        if len(refs) == 2:
            pair_def[name] = (refs[0], refs[1])
    if "data_kiemtra" not in ctes:
        raise ValueError("Không thấy mệnh đề data_kiemtra trong file SQL (danh sách cặp tương tác sử dụng).")
    used = []
    for n in re.findall(r"SELECT \* from (\w+)", ctes["data_kiemtra"], re.I):
        if n in pair_def and n not in used:
            used.append(n)
    pairs, seen = [], set()
    for n in used:
        a, b = pair_def[n]
        if a not in drugs or b not in drugs:
            warnings.append(f"Cặp {n}: hoạt chất {a if a not in drugs else b} chưa được định nghĩa - bỏ qua.")
            continue
        k = frozenset((a, b))
        if k in seen or a == b:
            continue
        seen.add(k)
        pairs.append([a, b])
    # canh bao: ma dung chung giua cac hoat chat khac nhau
    inv = defaultdict(set)
    for d, v in drugs.items():
        for c in v["codes"]:
            if re.match(r"^\d", c):
                inv[c].add(d)
    for c, ds in sorted(inv.items()):
        if len(ds) > 1:
            warnings.append(f"Mã {c} dùng chung cho: {', '.join(sorted(ds))} - kiểm tra lại mã trong file SQL.")
    return {"drugs": drugs, "pairs": pairs, "warnings": warnings}


def load_rules():
    _sync_bundled("Quy_tac_tuong_tac.json")
    for p in (CFG["data"] / "Quy_tac_tuong_tac.json", CFG["root"] / "TUONG_TAC" / "Quy_tac_tuong_tac.json"):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    raise FileNotFoundError("Chưa có bộ quy tắc tương tác (TUONG_TAC\\Quy_tac_tuong_tac.json). Hãy nạp file SQL.")


def save_rules(rules, source):
    _sync_bundled("Quy_tac_tuong_tac.json")
    rules = dict(rules)
    rules["source"] = source
    rules["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    atomic_write_json(CFG["data"] / "Quy_tac_tuong_tac.json", rules)
    return rules


# ----------------------------------------------------------------------------- co che / xu tri
KB_COLS = ["Thuốc 1", "Thuốc 2", "Cơ chế", "Hậu quả tương tác", "Xử trí"]


def ensure_kb():
    return _sync_bundled("Co_che_tuong_tac.xlsx")


_CACHE = {}


def _cached(path, build):
    """Doc file Excel lon (co dinh dang tran 16384 cot nen doc cham) 1 lan; doc lai khi file thay doi."""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path.name)
    if hit and hit[0] == key:
        return hit[1]
    val = build(path)
    _CACHE[path.name] = (key, val)
    return val


def load_kb():
    prepared = CFG.get("kb_json")
    if prepared is not None:
        return list(_cached(prepared, _read_kb_json))
    return list(_cached(ensure_kb(), read_kb_workbook))


def _read_kb_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_kb_workbook(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    try:
        aliases = {"a": ("thuoc 1", "hoat chat 1"), "b": ("thuoc 2", "hoat chat 2"),
                   "co_che": ("co che",), "hau_qua": ("hau qua tuong tac", "hau qua"),
                   "xu_tri": ("xu tri",), "muc_do": ("muc do",)}
        for ws in wb.worksheets:
            cols, header = {}, None
            # Source workbook has formatting extending to XFC: bound reads to real headers.
            for rowno, row in enumerate(ws.iter_rows(max_row=20, max_col=64, values_only=True), 1):
                hs = [norm(v) for v in row]
                found = {key: hs.index(nm) for key, names in aliases.items()
                         for nm in reversed(names) if nm in hs}
                if {"a", "b", "co_che", "hau_qua", "xu_tri"} <= found.keys():
                    cols, header = found, rowno
                    break
            if header is None:
                continue
            for rowno, row in enumerate(ws.iter_rows(min_row=header + 1, max_col=max(cols.values()) + 1,
                                                    values_only=True), header + 1):
                item = {key: str(row[col] if row[col] is not None else "").strip()
                        for key, col in cols.items()}
                if item["a"] and item["b"]:
                    item["source"] = f"{ws.title}!{rowno}"
                    out.append(item)
    finally:
        wb.close()
    if not out:
        raise ValueError("Bảng cơ chế cần các cột Thuốc/Hoạt chất 1, Thuốc/Hoạt chất 2, Cơ chế, Hậu quả, Xử trí.")
    return out


@functools.lru_cache(maxsize=8192)
def _drug_key(value):
    value = str(value).strip()
    # A combination labelled '(active ingredient)' is explicitly indexed by that ingredient.
    parent = re.search(r"\(([^()]+)\)\s*$", value)
    if "+" in value and parent:
        value = parent[1]
    key = norm(value).replace(" ", "")
    aliases = {
        "domperidone": "domperidon", "itraconazole": "itraconazol",
        "levodopacarbidopaentacapon": "levodopacarbidopa",
        "kalicloriddanguonggiaiphongkeodai": "kalicloridviengpkd",
    }
    return aliases.get(key, key)


def _same(x, y):
    return bool(_drug_key(x)) and _drug_key(x) == _drug_key(y)


def find_kb(kb, ta, tb):
    for e in kb:
        if (_same(e["a"], ta) and _same(e["b"], tb)) or (_same(e["a"], tb) and _same(e["b"], ta)):
            return e
    return None


# ----------------------------------------------------------------------------- doc xls/xlsx
FIELDS = {
    "mabn": ("ma y te", "mabn", "ma bn", "ma benh nhan"),
    "so_ba": ("so benh an",),
    "ten": ("ho va ten", "ho ten", "ten benh nhan"),
    "ns": ("nam sinh",),
    "ngay": ("ngay y lenh", "ngaychidinh", "ngay chi dinh"),
    "khoa_ra": ("khoa ra",),
    "khoa": ("ten khoa trai", "ten khoatrai", "khoa trai", "ten khoa", "khoa lam sang"),
    "noi": ("noi chi dinh",),
    "thuoc": ("ten duoc", "ten thuoc"),
    "ma_duoc": ("ma duoc", "ma thuoc"),
    "hc": ("hoat chat",),
    "ma": ("mahoatchat", "ma hoat chat"),
}


def _map(row):
    hs = [norm(c) for c in row]
    cols = {}
    for f, names in FIELDS.items():
        for nm in names:  # uu tien theo thu tu ten
            if nm in hs:
                cols[f] = hs.index(nm)
                break
    return cols


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    return "" if s.upper() in ("#N/A", "N/A", "NAN", "NULL", "#VALUE!", "#REF!") else s


def load_drug_codes():
    """Exact product-code lookup; never guess an ingredient from a brand name."""
    path = _sync_bundled("mahoatchat.xlsx")
    if not path.exists():
        raise FileNotFoundError("Thiếu TUONG_TAC/mahoatchat.xlsx để gán mã hoạt chất từ Mã dược.")
    return _cached(path, _read_codes)


def _read_codes(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    mapping, found = defaultdict(set), False
    try:
        for ws in wb.worksheets:
            header = None
            for i, row in enumerate(ws.iter_rows(max_row=20, max_col=32, values_only=True), 1):
                hs = [norm(v) for v in row]
                if "ma hoat chat" in hs and any(k in hs for k in ("ma", "ma duoc", "ma thuoc")):
                    pc = next(hs.index(k) for k in ("ma", "ma duoc", "ma thuoc") if k in hs)
                    ac = hs.index("ma hoat chat")
                    header, found = i, True
                    break
            if header is None:
                continue
            for row in ws.iter_rows(min_row=header + 1, max_col=max(pc, ac) + 1, values_only=True):
                # The supplied catalogue has an Excel column-number row directly after its header.
                if not isinstance(row[pc], str):
                    continue
                product, active = _code(_clean(row[pc])), _code(_clean(row[ac]))
                if product:
                    mapping[product]  # retain products with a blank active-ingredient code
                    if active:
                        mapping[product].add(active)
    finally:
        wb.close()
    if not found:
        raise ValueError("mahoatchat.xlsx cần có cột MÃ (hoặc Mã dược) và MÃ HOẠT CHẤT.")
    return dict(mapping)


def to_date(v, dmy_default=False, amb=None):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v or "").strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return datetime.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if not m:
        return None
    a, b, y = int(m[1]), int(m[2]), int(m[3])
    if a > 12:
        d, mo = a, b
    elif b > 12:
        mo, d = a, b
    else:
        if a != b and amb is not None:
            amb.append(1)
        d, mo = (a, b) if dmy_default else (b, a)
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def read_prescriptions(path, dmy=False):
    best = None
    for name, data in iter_sheets(path):
        for hi, row in enumerate(data[:20]):
            c = _map(row)
            if {"mabn", "ngay"} <= set(c) and {"ma", "ma_duoc"} & c.keys():
                score = (name.lower() == "tuongtacthuoc", len(c), len(data))
                if best is None or score > best[0]:
                    best = (score, name, data, hi, c)
                break
    if best is None:
        raise ValueError("Không thấy bảng kê thuốc: cần Mã y tế, Ngày Y Lệnh, Mã dược "
                         "hoặc định dạng cũ MaBN, ngaychidinh, mahoatchat.")
    _, sname, data, hi, c = best
    rows, bad_date, amb = [], 0, []
    catalogue = load_drug_codes() if "ma_duoc" in c else None
    code_stats = {"assigned": 0, "unknown": 0, "blank": 0, "ambiguous": 0}
    unmapped = set()
    if "ngay y lenh" == norm(data[hi][c["ngay"]]):
        dmy = True
    # suy ra dinh dang ngay cua ca file: co so >12 o vi tri dau -> d/m/y; o vi tri sau -> m/d/y
    first_big = second_big = 0
    for r in data[hi + 1:]:
        v = r[c["ngay"]] if c["ngay"] < len(r) else None
        mt = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", v) if isinstance(v, str) else None
        if mt:
            first_big += int(mt[1]) > 12
            second_big += int(mt[2]) > 12
    if first_big and not second_big:
        dmy = True
    elif second_big and not first_big:
        dmy = False
    for r in data[hi + 1:]:
        g = lambda k: r[c[k]] if k in c and c[k] < len(r) else None
        mabn = _clean(g("mabn"))
        if not mabn:
            continue
        d = to_date(g("ngay"), dmy, amb)
        if d is None:
            bad_date += 1
            continue
        product = _code(_clean(g("ma_duoc")))
        active = _code(_clean(g("ma")))
        if catalogue is not None:
            candidates = catalogue.get(product)
            active = ""
            if candidates is None:
                code_stats["unknown"] += 1
                unmapped.add(product or "(Mã dược trống)")
            elif not candidates:
                code_stats["blank"] += 1
                unmapped.add(product)
            elif len(candidates) != 1:
                code_stats["ambiguous"] += 1
                unmapped.add(product)
            else:
                active = next(iter(candidates))
                code_stats["assigned"] += 1
        rows.append({"mabn": mabn, "so_ba": _clean(g("so_ba")), "ten": _clean(g("ten")), "ns": _clean(g("ns")),
                     "day": d, "khoa": _clean(g("khoa")) or _clean(g("noi")) or _clean(g("khoa_ra")), "thuoc": _clean(g("thuoc")),
                     "hc": _clean(g("hc")), "ma": active, "ma_duoc": product})
    warn = []
    if catalogue is not None:
        for key, label in (("unknown", "Mã dược không tìm thấy trong danh mục"),
                           ("blank", "Mã hoạt chất trống trong danh mục"),
                           ("ambiguous", "Mã dược có nhiều mã hoạt chất khác nhau")):
            if code_stats[key]:
                warn.append(f"{code_stats[key]} dòng chưa gán mã: {label}. Không tự suy đoán mã hoạt chất.")
        if unmapped:
            warn.append("Mã dược cần kiểm tra: " + ", ".join(sorted(unmapped)[:40])
                        + (f"... (tổng {len(unmapped)} mã)." if len(unmapped) > 40 else "."))
    if bad_date:
        warn.append(f"Bỏ qua {bad_date} dòng không đọc được ngày chỉ định.")
    if amb:
        warn.append(f"{len(amb)} ngày có dạng mơ hồ (cả hai số ≤ 12) được hiểu là " + ("ngày/tháng/năm." if dmy else "tháng/ngày/năm (như dữ liệu xuất từ SQL)."))
    if not {"khoa", "noi", "khoa_ra"} & c.keys():
        warn.append("Không có cột Tên khoa/trại, Nơi chỉ định hoặc Khoa ra.")
    missing_ward = sum(not r["khoa"] for r in rows)
    if missing_ward:
        warn.append(f"{missing_ward} dòng chưa có thông tin khoa lâm sàng.")
    for k, lab in (("so_ba", "Số Bệnh Án"), ("ten", "Họ và Tên")):
        if k not in c:
            warn.append(f"Không có cột {lab}.")
    return rows, {"sheet": sname, "rows": len(rows), "warnings": warn,
                  "code_mapping": code_stats if catalogue is not None else None}


# ----------------------------------------------------------------------------- do tuong tac
def detect(rows, rules, by_name=False):
    code2d = defaultdict(set)
    for d, v in rules["drugs"].items():
        for c in v["codes"]:
            code2d[_code(c)].add(d)
    partner = defaultdict(dict)
    for a, b in rules["pairs"]:
        partner[a][b] = (a, b)
        partner[b][a] = (a, b)
    name_tok = {d: norm(d.replace("_", " ")) for d in rules["drugs"]} if by_name else {}

    groups = defaultdict(lambda: defaultdict(list))
    matched = 0
    for i, r in enumerate(rows):
        ds = set(code2d.get(r["ma"], ()))
        if not ds and by_name and not r["ma"] and r["hc"]:
            h = " " + norm(r["hc"]) + " "
            ds = {d for d, tk in name_tok.items() if tk and f" {tk} " in h}
        if ds:
            matched += 1
        for d in ds:
            groups[(r["mabn"], r["day"])][d].append(i)

    events = []
    for (mabn, day), dm in groups.items():
        for d in dm:
            for p, ab in partner.get(d, {}).items():
                if p in dm and d < p:
                    ra, rb = dm[ab[0]], dm[ab[1]]
                    if any(x != y for x in ra for y in rb):  # 2 dong thuoc khac nhau
                        events.append({"mabn": mabn, "day": day, "a": ab[0], "b": ab[1], "rows": sorted(set(ra) | set(rb))})
    events.sort(key=lambda e: (e["day"], e["mabn"], e["a"], e["b"]))
    return events, matched


def fmt_dates(days):
    days = sorted(set(days))
    by = OrderedDict()
    for d in days:
        by.setdefault((d.year, d.month), []).append(d)
    out = []
    for (y, m), ds in by.items():
        runs, start, prev = [], ds[0], ds[0]
        for d in ds[1:]:
            if d.toordinal() == prev.toordinal() + 1:
                prev = d
            else:
                runs.append((start, prev))
                start = prev = d
        runs.append((start, prev))
        toks = [f"{a.day:02d}" if a == b else f"{a.day:02d}-{b.day:02d}" for a, b in runs]
        if all(a == b for a, b in runs):
            out.append(",".join(toks) + f"/{m:02d}/{y}")
        else:
            out.append("\n".join(t + f"/{m:02d}/{y}" for t in toks))
    return "\n".join(out)


def aggregate(events, rows, rules, kb, month=None, year=None):
    """Gom ket qua cho bao cao."""
    if month and year:
        events = [e for e in events if e["day"].month == month and e["day"].year == year]
    ten = {d: v["ten"] for d, v in rules["drugs"].items()}
    pats = {}
    for e in events:
        rs = [rows[i] for i in e["rows"]]
        p = pats.setdefault(e["mabn"], {"mabn": e["mabn"], "so_ba": "", "ten": "", "ns": ""})
        for r in rs:
            for k in ("so_ba", "ten", "ns"):
                if r[k] and not p[k]:
                    p[k] = r[k]
        e["khoa"] = "; ".join(sorted({r["khoa"] for r in rs if r["khoa"]}))
        e["so_ba"] = next((r['so_ba'] for r in rs if r['so_ba']), '')
        e["noi"] = bool(e['so_ba'])
    pair_pat = defaultdict(set)
    for e in events:
        pair_pat[(e["a"], e["b"])].add(e["mabn"])
    pair_rows = sorted(pair_pat.items(), key=lambda kv: (-len(kv[1]), ten[kv[0][0]], ten[kv[0][1]]))
    detail = {True: OrderedDict(), False: OrderedDict()}
    for e in events:
        k = (e["mabn"], e["a"], e["b"], e["khoa"], e['so_ba'])
        detail[e["noi"]].setdefault(k, []).append(e["day"])

    def rows_of(noi):
        out = []
        for (mabn, a, b, khoa, so_ba), days in detail[noi].items():
            p = pats[mabn]
            out.append({"first": min(days), "dates": fmt_dates(days), "id": so_ba if noi else mabn,
                        "ten": p["ten"], "ns": p["ns"], "a": ten[a], "b": ten[b], "khoa": khoa})
        out.sort(key=lambda r: (r["first"], r["id"], r["a"]))
        return out

    missing, kb_rows = [], []
    for (a, b), _ in pair_rows:
        hit = find_kb(kb, ten[a], ten[b])
        kb_rows.append({"pair": f"{ten[a]} + {ten[b]}", "kb": hit})
        if not hit or any(not hit.get(k) for k in ("co_che", "hau_qua", "xu_tri")):
            missing.append(f"{ten[a]} + {ten[b]}")
    return {"pairs": [{"pair": f"{ten[a]} + {ten[b]}", "n": len(s)} for (a, b), s in pair_rows],
            "kb_rows": kb_rows, "missing": missing,
            "noi": rows_of(True), "ngoai": rows_of(False),
            "n_noi": len({e["mabn"] for e in events if e["noi"]}),
            "n_ngoai": len({e["mabn"] for e in events if not e["noi"]}),
            "n_events": len(events)}


def detect_period(rows):
    from collections import Counter
    c = Counter((r["day"].year, r["day"].month) for r in rows)
    if not c:
        return None
    (y, m), _ = c.most_common(1)[0]
    return m, y


# ----------------------------------------------------------------------------- Word
def make_report(out_path, month, year, R, template):
    from docx import Document
    doc = Document(str(template))
    if len(doc.tables) < 6:
        raise ValueError("Mẫu Word phải có đủ 6 bảng (tiêu đề, tóm tắt, chữ ký, Phụ lục I, II, III).")
    t_head, t_sum, _, t_kb, t_noi, t_ngoai = doc.tables[:6]
    nm, ny = (1, year + 1) if month == 12 else (month + 1, year)
    for p in t_head.rows[0].cells[1].paragraphs:
        if "ngày" in p.text and "tháng" in p.text:
            repl_group(p, r"năm\s*(\d{4})", str(ny))
            repl_group(p, r"tháng\s*[\.…\s]*(\d{1,2})", f"{nm:02d}")
    mm = f"{month:02d}/{year}"
    repl_group(find_par(doc, lambda t: t.startswith("Tương tác thuốc chống chỉ định")), r"tháng\s*(\d{1,2}/\d{4})", mm)
    p = find_par(doc, lambda t: t.startswith("Bộ phận dược lâm sàng"))
    repl_group(p, r"trong tháng\s*(\d{1,2})\s*năm", f"{month:02d}")
    repl_group(p, r"năm\s*(\d{4})\.\s*Qua", str(year))
    repl_group(p, r"có\s*(\d+)\s*bệnh án", str(R["n_noi"]))
    repl_group(p, r",\s*(\d+)\s*đơn thuốc", str(R["n_ngoai"]))
    repl_group(find_par(doc, lambda t: t.startswith("Trên đây là thông tin")), r"tháng\s*(\d{1,2}/\d{4})", mm)
    repl_group(find_par(doc, lambda t: re.match(r"Phụ lục I:", t)), r"tháng\s*(\d{1,2}\.\d{4})", f"{month}.{year}")

    fill_rows(t_sum, [[x["pair"], str(x["n"])] for x in R["pairs"]], "Không phát hiện cặp tương tác")
    fill_rows(t_kb, [[k["pair"],
                       (k["kb"] or {}).get("co_che") or "(chưa có trong bảng cơ chế)",
                       (k["kb"] or {}).get("hau_qua") or "(chưa có trong bảng cơ chế)",
                       (k["kb"] or {}).get("xu_tri") or "(chưa có xử trí trong bảng nguồn)"] for k in R["kb_rows"]],
               "Không có")
    fill_rows(t_noi, [[str(i), r["dates"], r["id"], r["ten"], r["ns"], r["a"], r["b"], r["khoa"]]
                       for i, r in enumerate(R["noi"], 1)], "Không có")
    fill_rows(t_ngoai, [[str(i), r["dates"], r["id"], r["ten"], r["ns"], r["a"], r["b"], r["khoa"]]
                         for i, r in enumerate(R["ngoai"], 1)], "Không có")
    save_document(doc,out_path)


# ----------------------------------------------------------------------------- quy trinh
def generate(path, month, year, by_name=False, dmy=False):
    rules = load_rules()
    kb = load_kb()
    rows, info = read_prescriptions(path, dmy)
    warnings = list(info["warnings"])
    events, matched = detect(rows, rules, by_name)
    R = aggregate(events, rows, rules, kb, month, year)
    allp = {e["mabn"] for e in events}
    inp = {e["mabn"] for e in events if e["day"].month == month and e["day"].year == year}
    out_of_period = len(allp - inp)
    if out_of_period > 0:
        warnings.append(f"{out_of_period} bệnh nhân có tương tác ngoài tháng {month:02d}/{year} đã được loại khỏi báo cáo.")
    if matched == 0:
        warnings.append("Không dòng nào khớp mã hoạt chất trong bộ quy tắc - kiểm tra cột mahoatchat (có thể vlookup bị #N/A).")
    if R["missing"]:
        warnings.append("Chưa có cơ chế/xử trí cho: " + "; ".join(R["missing"]) + ". Hãy bổ sung vào Co_che_tuong_tac.xlsx rồi tạo lại.")
    template = CFG["root"] / "TUONG_TAC" / "Mau_tuong_tac_thuoc.docx"
    if not template.exists():
        raise FileNotFoundError(f"Không thấy file mẫu Word: {template}")
    name = f"Tuong_tac_thuoc_thang_{month:02d}_nam_{year}.docx"
    out = CFG["data"] / "Bao_cao" / name
    make_report(out, month, year, R, template)
    return {"ok": True, "name": name, "path": str(out), "warnings": warnings,
            "summary": {"rows": info["rows"], "matched": matched, "sheet": info["sheet"], "n_noi": R["n_noi"],
                        "code_mapping": info.get("code_mapping"),
                        "n_ngoai": R["n_ngoai"], "pairs": R["pairs"], "missing": R["missing"],
                        "n_noi_rows": len(R["noi"]), "n_ngoai_rows": len(R["ngoai"])}}


def make_blueprint():
    from flask import Blueprint, jsonify, request
    bp = Blueprint("ttt", __name__)
    file_routes(bp, "ttt", lambda: CFG["data"] / "Bao_cao", (".docx",))

    @bp.get("/api/ttt/state")
    def state():
        today = datetime.date.today()
        m, y = (12, today.year - 1) if today.month == 1 else (today.month - 1, today.year)
        try:
            ru = load_rules()
            info = {"drugs": len(ru["drugs"]), "pairs": len(ru["pairs"]), "source": ru.get("source", ""),
                    "updated": ru.get("updated", ""), "warnings": ru.get("warnings", [])}
        except Exception as e:
            ru, info = None, {"error": str(e)}
        kb_error, covered, missing, nkb = "", 0, [], 0
        try:
            kb = load_kb()
            nkb = len(kb)
            for a, b in (ru["pairs"] if ru else []):
                ta, tb = ru["drugs"][a]["ten"], ru["drugs"][b]["ten"]
                hit = find_kb(kb, ta, tb)
                if hit and all(hit.get(k) for k in ("co_che", "hau_qua", "xu_tri")):
                    covered += 1
                else:
                    missing.append(f"{ta} + {tb}")
        except Exception as e:
            kb_error = str(e)
        return jsonify(month=m, year=y, rules=info, kb=nkb, kb_error=kb_error, kb_covered=covered, kb_missing=missing,
                       template=(CFG["root"] / "TUONG_TAC" / "Mau_tuong_tac_thuoc.docx").exists())

    @bp.post("/api/ttt/inspect")
    @safe
    def inspect():
        with upload("file") as p:
            rows, info = read_prescriptions(p, request.form.get("dmy") == "1")
        per = detect_period(rows)
        ev, matched = detect(rows, load_rules(), request.form.get("by_name") == "1")
        return jsonify(ok=True, rows=info["rows"], sheet=info["sheet"], warnings=info["warnings"], matched=matched,
                       code_mapping=info.get("code_mapping"), month=per[0] if per else None, year=per[1] if per else None,
                       events=len(ev))

    @bp.post("/api/ttt/generate")
    @guarded(_LOCK, ("docx",), perm="Không ghi được file Word. Nếu đang mở file báo cáo cũ trong Word thì hãy đóng lại rồi thử lại.")
    def gen():
        o = json.loads(request.form.get("opts", "{}"))
        with upload("file") as p:
            if not p:
                return jsonify(ok=False, msg="Chưa chọn file xls/xlsx.")
            res = generate(p, int(o["month"]), int(o["year"]), bool(o.get("by_name")), bool(o.get("dmy")))
        res.pop("path", None)
        return jsonify(res)

    @bp.post("/api/ttt/rules")
    @safe
    def rules_upload():
        with upload("file", (".txt", ".sql")) as p:
            if not p:
                return jsonify(ok=False, msg="Chưa chọn file SQL (.txt/.sql).")
            raw = p.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        r = parse_sql(text)
        save_rules(r, request.files["file"].filename)
        return jsonify(ok=True, drugs=len(r["drugs"]), pairs=len(r["pairs"]), warnings=r["warnings"])

    @bp.post("/api/ttt/open-kb")
    def open_kb():
        if os.name != "nt":
            return jsonify(ok=False, msg="Chỉ mở được trên Windows.")
        os.startfile(str(ensure_kb()))
        return jsonify(ok=True)

    return bp
