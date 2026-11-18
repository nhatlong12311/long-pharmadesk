# -*- coding: utf-8 -*-
"""
Pharma Desk - Bao cao phan tich ABC/VEN (V2.6)
Nguon vao: file Excel (danh muc thuoc su dung trong thang) -> phan tich ABC/VEN -> dien vao mau Word.
Chi dung openpyxl/xlrd/python-docx (khong nap pandas) de mo nhanh.
"""
import bisect, copy, datetime, json, math, re, threading
from pathlib import Path

from common import data_directory, save_document, iter_sheets, atomic_write_json, save_data_workbook, fill_rows, file_routes, find_par, guarded, norm, read_sheets, repl_group, safe, set_cell, set_par, upload

CFG = {"root": Path("."), "data": Path(".")}
_LOCK = threading.Lock()

# ----------------------------------------------------------------------------- tien ich
def num(v):
    if v is None or isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        value = float(v)
        if not math.isfinite(value):
            raise ValueError("Số liệu phải là số hữu hạn.")
        return value
    s = str(v).strip().replace(" ", "")
    if not s:
        return 0.0
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    try:
        value = float(s)
    except ValueError:
        raise ValueError(f"Số liệu không hợp lệ: {v!r}") from None
    if not math.isfinite(value):
        raise ValueError("Số liệu phải là số hữu hạn.")
    return value


def validate_period(month, year):
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise ValueError("Tháng hoặc năm báo cáo không hợp lệ.")


def f0(n):
    return f"{int(round(n)):,}".replace(",", ".")


def pct(x, d=2):
    return f"{x:.{d}f}".replace(".", ",") + "%"


def word(d):
    return "tăng" if d > 0 else "giảm" if d < 0 else "không đổi"


def prev_period(m, y):
    return (12, y - 1) if m == 1 else (m - 1, y)


def next_period(m, y):
    return (1, y + 1) if m == 12 else (m + 1, y)


def init(root, data_dir):
    CFG["root"] = Path(root)
    CFG["data"] = Path(data_dir)
    for sub in ("Lich_su", "Bao_cao"):
        (data_directory(CFG) / sub).mkdir(parents=True, exist_ok=True)


def _map_header(row):
    hs = [norm(c) for c in row]
    cols, used = {}, set()

    def take(field, test):
        if field in cols:
            return
        for i, h in enumerate(hs):
            if i in used or not h:
                continue
            if test(h):
                cols[field] = i
                used.add(i)
                return

    take("ma", lambda h: h in ("ma duoc", "ma thuoc"))
    take("ten", lambda h: h == "ten thuoc")
    take("ten", lambda h: h.startswith("ten thuoc") or h == "ten biet duoc")
    take("hc", lambda h: h in ("hoat chat", "ten hoat chat"))
    take("hl", lambda h: h in ("ham luong", "nong do ham luong"))
    take("qc", lambda h: h in ("quy cach", "quy cach dong goi", "quy cach dong goi thuoc"))
    take("ven", lambda h: h == "ven")
    take("nuoc", lambda h: h.startswith("nuoc san xuat") or h == "nuoc sx")
    take("dvt", lambda h: h in ("dvt", "don vi tinh"))
    take("gia", lambda h: h in ("don gia", "gia", "don gia binh quan"))
    take("sl", lambda h: "so luong" in h or h.startswith("bhyt") or h == "sl")
    take("tt", lambda h: "thanh tien" in h or h == "thanhtien")
    take("hang", lambda h: h in ("phan hang", "phan hang abc", "hang abc", "hang"))
    take("nhom", lambda h: h in ("phan nhom", "nhom"))
    take("stt", lambda h: h == "stt")
    return cols


def _valid_header(c):
    return "ten" in c and "ven" in c and ("tt" in c or ("gia" in c and "sl" in c))


def read_drug_file(path, sheet=None):
    """Tra ve (rows, info). Tu chon sheet phu hop nhat neu sheet=None."""
    best = None
    for name, data in iter_sheets(path, sheet):
        if sheet and name != sheet:
            continue
        for hi, row in enumerate(data[:15]):
            c = _map_header(row)
            if _valid_header(c):
                score = len(c) + (3 if "hang" in c else 0) + (2 if "ma" in c else 0)
                n = len(data) - hi - 1
                if best is None or (score, n) > (best[0], best[1]):
                    best = (score, n, name, data, hi, c)
                break
    if best is None:
        raise ValueError("Không tìm thấy bảng thuốc trong file Excel. Cần có các cột: Tên thuốc, VEN và Thành tiền "
                         "(hoặc Đơn giá + Số lượng).")
    _, _, sname, data, hi, c = best
    rows, warn, bad_ven, skipped = [], [], [], 0
    g = lambda r, k: (r[c[k]] if k in c and c[k] < len(r) else None)
    for r in data[hi + 1:]:
        ten = str(g(r, "ten") or "").strip()
        if not ten or norm(ten) in ("grand total", "total", "tong", "tong cong"):
            continue
        gia, sl, tt = num(g(r, "gia")), num(g(r, "sl")), num(g(r, "tt"))
        if tt <= 0 and gia > 0 and sl > 0:
            tt = gia * sl
        if tt <= 0:
            skipped += 1
            continue
        ma = str(g(r, "ma") or "").strip()
        if not ma and "stt" in c:
            s = g(r, "stt")
            if isinstance(s, str) and re.search(r"[A-Za-z]", s):
                ma = s.strip()  # file thang cu dat ma duoc o cot STT
        ven = str(g(r, "ven") or "").strip().upper()[:1]
        if ven not in ("V", "E", "N"):
            bad_ven.append(ten)
            ven = "E"
        hang = str(g(r, "hang") or "").strip().upper()[:1]
        rows.append({"ma": ma, "ten": ten, "hc": str(g(r, "hc") or "").strip(),
                     "hl": str(g(r, "hl") or "").strip(), "qc": str(g(r, "qc") or "").strip(), "ven": ven,
                     "dvt": str(g(r, "dvt") or "").strip(), "gia": gia, "sl": sl, "tt": tt,
                     "hang": hang if hang in ("A", "B", "C") else ""})
    if not rows:
        raise ValueError("Bảng thuốc không có dòng nào có Thành tiền > 0.")
    if bad_ven:
        warn.append(f"{len(bad_ven)} thuốc thiếu/sai nhóm VEN (đã tạm tính là E): " + ", ".join(bad_ven[:5]) +
                    (" ..." if len(bad_ven) > 5 else ""))
    if skipped:
        warn.append(f"Bỏ qua {skipped} dòng có thành tiền bằng 0.")
    if "hc" not in c:
        warn.append("File không có cột Hoạt chất: mục theo dõi hoạt chất (Colistin, Meropenem...) sẽ trống.")
    info = {"sheet": sname, "rows": len(rows), "total": sum(x["tt"] for x in rows),
            "has_class": all(x["hang"] for x in rows), "warnings": warn}
    return rows, info


# ----------------------------------------------------------------------------- 4 nguon xuat + danh muc

def _read_strict_catalog(path):
    """Fallback for ISO Strict OOXML exports (not handled by older openpyxl)."""
    import zipfile, xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            shared = [''.join(t.text or '' for t in si.iter() if t.tag.endswith('}t')) for si in root]
        names = [x for x in z.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', x, re.I)]
        if not names: raise ValueError('Không tìm thấy sheet trong danh mục.')
        all_rows = []
        with z.open(names[0]) as stream:
            for _, el in ET.iterparse(stream, events=('end',)):
                if not el.tag.endswith('}row'): continue
                cells = [None] * 35
                for cell in el:
                    if not cell.tag.endswith('}c'): continue
                    ref = cell.attrib.get('r',''); letters = re.match(r'[A-Z]+',ref)
                    if not letters: continue
                    col = 0
                    for ch in letters.group():col=col*26+ord(ch)-64
                    if col > 35: continue
                    val = next((x.text for x in cell if x.tag.endswith('}v')),None)
                    if cell.attrib.get('t') == 's' and val is not None:val=shared[int(val)]
                    if cell.attrib.get('t') == 'inlineStr':
                        val=''.join(x.text or '' for x in cell.iter() if x.tag.endswith('}t'))
                    cells[col-1] = val
                all_rows.append(cells)
                el.clear()
        return all_rows


def _valid_drug_code(code):
    # Ma duoc hop le co the co dau cach, cham, gach cheo, dau ngoac kep.
    # Khong ep ve ma chu-so thuan vi se lam mat thuoc dang su dung.
    return bool(code and len(code) >= 4 and re.search(r'[A-Z]', code)
                and code not in ('MA DUOC', 'MA THUOC'))


def _load_catalog(path):
    try:
        sheets=read_sheets(path)
        data=max((rows for _,rows in sheets),key=len)
    except Exception:
        data=_read_strict_catalog(path)
    found={}; duplicates=[]
    for line, r in enumerate(data,1):
        if len(r)<27: continue
        code=str(r[1] or '').strip().upper()
        if not _valid_drug_code(code):continue
        item={'ma':code,'ten':str(r[2] or '').strip(),'hl':str(r[5] or '').strip(),
              'hc':str(r[4] or '').strip(),'dvt':str(r[8] or '').strip(),
              'qc':str(r[10] or '').strip(),
              'ven':str(r[26] or '').strip().upper()[:1], 'line':line}
        if not item['ten']:continue
        if code in found:
            old=found[code]
            if (norm(old['ten']),norm(old['hl']),norm(old['qc']),old['ven']) != (norm(item['ten']),norm(item['hl']),norm(item['qc']),item['ven']):
                duplicates.append(code)
        else:found[code]=item
    if not found: raise ValueError('Danh mục không có mã thuốc hợp lệ ở cột B.')
    return found,duplicates


def _reported_name(raw):
    # Remove manufacturer/batch decorations, not the drug strength itself.
    name=str(raw or '').strip().split(' (')[0].strip()
    return name


def _volume(text):
    m=re.search(r'(\d+(?:[.,]\d+)?)\s*ml\b',norm(text))
    return m.group(1) if m else ''


def prepare_four_files(khu,bhyt,noi,dm):
    """Returns current ABC/VEN rows and review list; no silent name-based approval."""
    catalog,duplicates=_load_catalog(dm)
    warnings=[]; reviews=[]; raw=[]; stats={}
    if duplicates:warnings.append(f'{len(set(duplicates))} mã lặp có thông tin khác nhau trong danh mục; ưu tiên dòng đầu, cần kiểm tra.')
    for name,path in [('Ngoại trú khu C',khu),('Ngoại trú BHYT',bhyt),('Nội trú',noi)]:
        sheets=read_sheets(path)
        data=max((rows for _,rows in sheets),key=len)
        count=0; invalid=0
        for rowno,r in enumerate(data,1):
            g=lambda i: r[i] if i<len(r) else None
            code=str(g(1) or '').strip().upper()
            if not _valid_drug_code(code):continue
            if name=='Nội trú':
                P=num(g(15)); J=num(g(9)); Q=num(g(16))
                qty=P-J
                if qty<=0:continue
                if P<=0:
                    reviews.append({'source':name,'row':rowno,'ma':code,'status':'Lỗi P = 0','note':'Không tính được Q/P'})
                    invalid+=1;continue
                price=Q/P
            else:
                qty=num(g(4));price=num(g(6))
                if qty<=0:continue
            if price<=0:
                invalid+=1
                reviews.append({'source':name,'row':rowno,'ma':code,'status':'Đơn giá không hợp lệ','note':'Kiểm tra cột nguồn'})
                continue
            item=catalog.get(code)
            status='Theo mã'; note=''
            if item is None:
                reported=_reported_name(g(2))
                n=norm(reported)
                candidates=[x for x in catalog.values() if norm(x['ten'])==n]
                if not candidates:
                    candidates=[x for x in catalog.values() if n.startswith(norm(x['ten'])+' ') and len(norm(x['ten']))>=8]
                # Only accept one unique catalog drug name, and compatible volume if volume appears.
                names={norm(x['ten']) for x in candidates}
                vols=_volume(reported)
                candidates=[x for x in candidates if not vols or vols in norm(x['hl']) or vols in norm(x['ten'])]
                if re.search(r'\d+(?:[.,]\d+)?\s*mg\s*/\s*1\s*ml',str(g(2) or ''),re.I) and not any('mg1ml' in norm(x['hl']).replace(' ','') for x in candidates):
                    candidates=[]
                if candidates and len(names)==1 and len({(norm(x['hl']),norm(x['qc'])) for x in candidates})==1:
                    item=candidates[0];status='Tự tìm theo tên/hàm lượng/quy cách'
                    note='Đề xuất '+item['ma']+'; người dùng cần kiểm tra lại trước khi chấp nhận.'
                else:
                    status='Chưa đối chiếu';note='Giữ tên từ file xuất, VEN tạm E; cần xác minh.'
            if item:
                ten=item['ten'];hl=item['hl'];qc=item['qc'];ven=item['ven'];hc=item['hc'];dvt=item['dvt']
            else:
                ten=_reported_name(g(2));hl='';qc='';ven='';hc='';dvt=str(g(3) or '') if name!='Nội trú' else ''
            if ven not in ('V','E','N'):
                status = status+' / Chưa có VEN';note=(note+'; ' if note else '')+'VEN sẽ được tạm tính E khi phân tích.'
                ven='E'
            if not qc:
                status = status+' / Thiếu quy cách'
                note=(note+'; ' if note else '')+'Không có quy cách trong danh mục; cần kiểm tra để tránh gộp nhầm.'
            if status!='Theo mã':
                reviews.append({'source':name,'row':rowno,'ma':code,'ten':ten,'hl':hl,'qc':qc,'status':status,'note':note})
            raw.append({'ma':code,'ten':ten,'hl':hl,'qc':qc,'hc':hc,'dvt':dvt,'ven':ven,
                        'sl':qty,'tt':qty*price,'gia':price,'hang':''})
            count+=1
        stats[name]={'rows':count,'invalid':invalid}
    # Preserve the first encountered drug code and accumulate total quantities and monetary values.
    grouped={}; seen_ven={}
    for r in raw:
        identity=(norm(r['ten']),norm(r['hl']),norm(r['qc']))
        prior=seen_ven.setdefault(identity,set())
        if prior and r['ven'] not in prior:
            reviews.append({'source':'Gộp','row':None,'ma':r['ma'],'status':'VEN không thống nhất',
                            'note':'Giữ riêng các mặt hàng khác VEN; cần xác minh danh mục.'})
        prior.add(r['ven'])
        # Missing packaging/strength must not erase the distinction between product codes.
        uncertain=r['ma'] if not r['qc'] or not r['hl'] else ''
        k=identity+(r['ven'],norm(r['dvt']),uncertain)
        if k not in grouped:grouped[k]=dict(r)
        else:
            dst=grouped[k];dst['sl']+=r['sl'];dst['tt']+=r['tt']
            if dst['ven'] != r['ven']:
                reviews.append({'source':'Gộp','row':None,'ma':dst['ma'],'status':'VEN không thống nhất',
                                'note':f"Cùng tên/hàm lượng/quy cách nhưng VEN khác: {dst['ven']} / {r['ven']}."})
    rows=list(grouped.values())
    for r in rows:r['gia']=r['tt']/r['sl']
    missing_qc=sum(not r['qc'] for r in rows)
    if missing_qc:
        warnings.append(f'{missing_qc} mặt hàng chưa có quy cách; xem sheet cảnh báo để kiểm tra, không tự gán quy cách.')
    warnings.append(f'{len(reviews)} cảnh báo cần rà soát. Kết quả tự dò tên/hàm lượng/quy cách chỉ là gợi ý, không phải xác nhận.')
    info={'rows':len(rows),'total':sum(r['tt'] for r in rows),'raw_rows':len(raw),
          'warnings':warnings,'reviews':reviews,'sources':stats,'has_class':False}
    if not rows:raise ValueError('Không có dòng thuốc hợp lệ trong ba file xuất.')
    return rows,info

# ----------------------------------------------------------------------------- phan tich
def nhom_of(hang, ven):
    if hang == "A" or (hang in ("B", "C") and ven == "V"):
        return "I"
    if hang == "C" and ven == "N":
        return "III"
    return "II"


def classify(rows, use_existing=False, a_pct=78.0, b_pct=95.0):
    """ABC: A 75-80% kinh phi, B 15-20%, kiem tra moi nhom 10-20% mat hang.

    Neu khong co cach chia thoa ca hai tieu chi, uu tien khoang kinh phi,
    sau do canh bao ty le mat hang; tuyet doi khong ep du lieu sai.
    """
    if not (math.isfinite(a_pct) and math.isfinite(b_pct) and 0 < a_pct < b_pct <= 100):
        raise ValueError('Ngưỡng ABC phải là số hữu hạn và thỏa 0 < A < A+B ≤ 100.')
    rows.sort(key=lambda r: -r["tt"])
    n = len(rows)
    total = sum(r["tt"] for r in rows)
    if use_existing and all(r["hang"] for r in rows):
        method = "Dùng cột Phân hạng có sẵn trong file (vẫn kiểm tra ngưỡng ABC)"
    elif n == 1 and total > 0:
        rows[0]['hang'] = 'A'
        method = 'Danh mục có một thuốc: xếp A và cảnh báo các tỷ lệ không đạt ngưỡng.'
    elif n and total > 0:
        prefix = [0.0]
        for r in rows:
            prefix.append(prefix[-1] + r["tt"])
        shares = [v / total * 100 for v in prefix]
        # The A/B cut is after items i and j, so every drug belongs to one group.
        # Find boundaries within financial bands; prioritize both item-count bands if feasible.
        a_candidates = [i for i in range(1,n) if 75 <= shares[i] <= 80]
        if not a_candidates:
            a_candidates = [min(range(1,n+1),key=lambda i:abs(shares[i]-a_pct))]
        # Uu tien A va B KHAC so luong mat hang, nhung khong pha vo nguong.
        # Neu co phuong an: A nhieu hon B toi thieu ~1.7% tong so mat hang,
        # trong khi A/B van thoa ca nguong chi phi va 10-20% mat hang.
        # Neu khong the thoa, quay ve tim nganh tai chinh gan muc dich.
        best_distinct, best_valid, best_financial, best_fallback = None, None, None, None
        min_count_gap = max(1, int(round(n * 0.017)))
        for i in a_candidates:
            # Scores are monotone on either side of their targets. Only target
            # neighbours and constraint boundaries can be optimal; preserve the
            # original scoring/tie-breaking without the quadratic full scan.
            boundaries=[i+1,n,i+math.ceil(n*.10),i+math.floor(n*.20),
                        i+round(n*.15),2*i-min_count_gap]
            boundaries += [bisect.bisect_left(shares, shares[i]+target)
                           for target in (15,20,b_pct-a_pct,15.5)]
            candidates={j for b in boundaries for j in range(b-2,b+3) if i<j<=n}
            for j in sorted(candidates):
                a_money = shares[i]
                b_money = shares[j] - shares[i]
                b_count = j-i
                financial = 75 <= a_money <= 80 and 15 <= b_money <= 20
                item_ok = 10 <= i/n*100 <= 20 and 10 <= b_count/n*100 <= 20
                score = (abs(a_money-a_pct)+abs(b_money-(b_pct-a_pct)),
                         abs(i/n*100-15)+abs(b_count/n*100-15), i, j)
                # For distinct groups keep a little margin within the cost bands.
                distinct_score = (abs(a_money-75.6)+abs(b_money-15.5),
                                  abs(i/n*100-18.5)+abs(b_count/n*100-17),i,j)
                if financial and item_ok and i-b_count >= min_count_gap:
                    if best_distinct is None or distinct_score < best_distinct[0]:
                        best_distinct=(distinct_score,i,j)
                if financial and item_ok and (best_valid is None or score < best_valid[0]):
                    best_valid = (score,i,j)
                if financial and (best_financial is None or score < best_financial[0]):
                    best_financial = (score,i,j)
                if best_fallback is None or score < best_fallback[0]:
                    best_fallback=(score,i,j)
        _,cut_a,cut_b = best_distinct or best_valid or best_financial or best_fallback
        for k,r in enumerate(rows):
            r["hang"] = "A" if k < cut_a else "B" if k < cut_b else "C"
        method = ("Tự phân ABC theo giá trị giảm dần: A 75–80% kinh phí, "
                  "B 15–20% kinh phí, kiểm tra A/B mỗi nhóm 10–20% mặt hàng; "
                  "ưu tiên khác số chủng loại A/B nếu vẫn đạt cả hai tiêu chí")
    else:
        method = "Không đủ số liệu để phân ABC"
    for r in rows:
        r["nhom"] = nhom_of(r["hang"], r["ven"])
    return method


def abc_rule_warnings(A):
    """Warn if the data cannot satisfy cost and SKU bands together."""
    warnings=[]
    n, total = A["n"], A["total"]
    if not n or not total:
        return ["Không có đủ dữ liệu giá trị để kiểm tra ABC."]
    for k, low, high in (("A",75,80),("B",15,20)):
        s=A["abc"][k]
        value_pct=s["v"]/total*100
        item_pct=s["n"]/n*100
        if not low-1e-8 <= value_pct <= high+1e-8:
            warnings.append(f"ABC nhóm {k}: giá trị {value_pct:.2f}% ngoài mức {low}–{high}% - cần kiểm tra.")
        if not 10-1e-8 <= item_pct <= 20+1e-8:
            warnings.append(f"ABC nhóm {k}: {s['n']}/{n} mặt hàng ({item_pct:.2f}%), ngoài mức 10–20%; "
                            "không tự ép tỷ lệ mặt hàng làm sai tỷ trọng kinh phí.")
    return warnings


def analyze(rows):
    total = sum(r["tt"] for r in rows)
    n = len(rows)

    def agg(keyf, keys):
        o = {}
        for k in keys:
            s = [r for r in rows if keyf(r) == k]
            o[k] = {"n": len(s), "v": sum(r["tt"] for r in s)}
        return o

    a = {"n": n, "total": total,
         "ven": agg(lambda r: r["ven"], "VEN"),
         "abc": agg(lambda r: r["hang"], "ABC"),
         "mat": agg(lambda r: r["nhom"], ["I", "II", "III"])}
    a["an"] = [r for r in rows if r["hang"] == "A" and r["ven"] == "N"]
    a["av"] = [r for r in rows if r["hang"] == "A" and r["ven"] == "V"]
    return a


def drug_key(r):
    identity = [norm(r.get(k, '')) for k in ('ten','hl','qc','dvt')]
    if not r.get('qc') or not r.get('hl'):
        identity.append(str(r.get('ma') or '').strip().upper())
    return '|'.join(identity)


# ----------------------------------------------------------------------------- lich su
def _hist_path(m, y):
    return data_directory(CFG) / "Lich_su" / f"{y}-{m:02d}.json"


def save_period(m, y, rows=None, stats=None, method=None):
    p = _hist_path(m, y)
    d = load_period(m, y) or {"month": m, "year": y}
    if rows is not None:
        d["rows"] = rows
    if stats is not None:
        d["stats"] = stats
    if method:
        d["method"] = method
    d["saved"] = datetime.datetime.now().isoformat(timespec="seconds")
    atomic_write_json(p, d)


def load_period(m, y):
    p = _hist_path(m, y)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


# ----------------------------------------------------------------------------- so lieu kinh phi
STAT_FIELDS = [
    ("noitru", "Kinh phí thuốc nội trú (đồng)"),
    ("ngoai_tay", "Kinh phí thuốc ngoại trú Tây y (đồng)"),
    ("bn_tay", "Số bệnh nhân ngoại trú lãnh thuốc Tây y"),
    ("bq_tay", "Kinh phí bình quân/toa Tây y (đồng)"),
    ("dongy", "Kinh phí thuốc Đông y (đồng)"),
    ("bq_dong", "Kinh phí bình quân/toa Đông y (đồng)"),
    ("bn_dong", "Số bệnh nhân ngoại trú lãnh thuốc Đông y"),
    ("hs_noitru", "Số hồ sơ nhập viện nội trú"),
]


def _stat_key(label):
    h = norm(label)
    if not h:
        return None
    if "ho so" in h:
        return "hs_noitru"
    if "binh quan" in h:
        return "bq_tay" if "tay y" in h else "bq_dong" if "dong y" in h else None
    if "benh nhan" in h:
        return "bn_tay" if "tay y" in h else "bn_dong" if "dong y" in h else None
    if "kinh phi" in h:
        if "dong y" in h:
            return "dongy"
        if "ngoai tru" in h and "tay y" in h:
            return "ngoai_tay"
        if "noi tru" in h:
            return "noitru"
    return None


def parse_stats(path, month):
    """Doc bang so sanh kinh phi: cot 'Thang N'. Tra ve {cur, prev, found}."""
    best = {}
    for _, data in read_sheets(path):
        hdr_i, months = None, {}
        for i, row in enumerate(data[:10]):
            m = {}
            for j, c in enumerate(row):
                h = norm(c)
                mm = re.fullmatch(r"thang (\d{1,2})", h)
                if mm:
                    m[int(mm[1])] = j
            if m:
                hdr_i, months = i, m
                break
        if hdr_i is None:
            continue
        vals = {mo: {} for mo in months}
        for row in data[hdr_i + 1:]:
            k = _stat_key(row[0] if row else None)
            if not k:
                continue
            for mo, j in months.items():
                v = row[j] if j < len(row) else None
                if v not in (None, ""):
                    vals[mo][k] = num(v)
        if sum(len(v) for v in vals.values()) > sum(len(v) for v in best.values()):
            best = vals
    pm = month - 1 if month > 1 else 12
    return {"cur": best.get(month, {}), "prev": best.get(pm, {}), "months": sorted(best)}


# ----------------------------------------------------------------------------- hoat chat theo doi
DEFAULT_WATCH = [
    {"id": "colistin", "on": True, "kw": ["colistin"], "mode": "total",
     "title": "Kháng sinh nhóm Colistin", "summary": "Kháng sinh nhóm Colistin chiếm kinh phí"},
    {"id": "meropenem", "on": True, "kw": ["meropenem"], "mode": "detail",
     "title": "Kháng sinh nhóm thuốc biệt dược:", "sub": "Hoạt chất Meropenem",
     "summary": "Tình hình sử dụng kháng sinh hoạt chất Meropenem", "brand": ["Meronem"],
     "recommend": "Đề nghị tăng cường sử dụng thêm nhóm kháng sinh meropenem loại giá thấp là {ds} "
                  "để giảm kinh phí sử dụng thuốc của bệnh viện."},
    {"id": "albumin", "on": True, "kw": ["albumin"], "mode": "detail",
     "title": "Tình hình sử dụng Albumin:", "summary": "Tình hình sử dụng thuốc hoạt chất Albumin"},
    {"id": "rivaroxaban", "on": True, "kw": ["rivaroxaban"], "mode": "detail",
     "title": "Tình hình sử dụng thuốc chống đông Rivaroxaban:",
     "summary": "Tình hình sử dụng thuốc hoạt chất Rivaroxaban"},
    {"id": "sevofluran", "on": True, "kw": ["sevofluran"], "mode": "detail",
     "title": "Tình hình sử dụng thuốc gây mê hoạt chất Sevofluran:",
     "summary": "Tình hình sử dụng thuốc hoạt chất Sevofluran"},
    {"id": "ticagrelor", "on": True, "kw": ["ticagrelor"], "hl": ["90"], "mode": "detail",
     "title": "Tình hình sử dụng hoạt chất Ticagrelor 90mg:",
     "summary": "Tình hình sử dụng thuốc hoạt chất Ticagrelor 90mg"},
]


def load_watch():
    p = data_directory(CFG) / "hoat_chat_theo_doi.json"
    if p.exists():
        try:
            w = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(w, list) and w:
                return w
        except Exception:
            pass
    return copy.deepcopy(DEFAULT_WATCH)


def save_watch(items):
    clean = []
    old = {x.get("id"): x for x in load_watch()}
    for i, it in enumerate(items):
        kw = [k.strip() for k in (it.get("kw") or []) if str(k).strip()]
        if not kw:
            continue
        base = copy.deepcopy(old.get(it.get("id"), {}))
        base.update({"id": it.get("id") or f"w{i}_{int(datetime.datetime.now().timestamp())}",
                     "on": bool(it.get("on", True)), "kw": kw,
                     "mode": "total" if it.get("mode") == "total" else "detail",
                     "title": (it.get("title") or "").strip() or kw[0].capitalize(),
                     "summary": (it.get("summary") or "").strip() or ("Tình hình sử dụng thuốc hoạt chất " + kw[0].capitalize())})
        clean.append(base)
    atomic_write_json(data_directory(CFG) / "hoat_chat_theo_doi.json", clean)
    return clean


def _match(rows, spec):
    kws = [norm(k) for k in spec.get("kw", [])]
    hls = [norm(k) for k in spec.get("hl", [])]
    out = []
    for r in rows:
        h = norm(r.get("hc", ""))
        if any(k and k in h for k in kws) and (not hls or any(x in norm(r.get("hl", "")) for x in hls)):
            out.append(r)
    return out


def _group(rows):
    g = {}
    for r in rows:
        k = drug_key(r)
        e = g.setdefault(k, {"ten": r["ten"], "hl": r.get("hl", ""), "dvt": r["dvt"], "gia": r["gia"], "sl": 0.0, "tt": 0.0})
        e["sl"] += r["sl"]
        e["tt"] += r["tt"]
    for entry in g.values():
        entry['gia'] = entry['tt']/entry['sl'] if entry['sl'] else 0.0
    return g


def watch_lines(cur_rows, prev_rows, spec, m, pm):
    """Tra ve (cac dong thuoc, tong_cur, tong_prev|None)."""
    cg = _group(_match(cur_rows, spec))
    pg = _group(_match(prev_rows, spec)) if prev_rows is not None else None
    items = []
    for k in set(cg) | set(pg or {}):
        c, p = cg.get(k), (pg or {}).get(k)
        src = c or p
        items.append({"ten": (c or p)["ten"], "hl": src["hl"], "dvt": src["dvt"], "gia": src["gia"],
                      "cq": c["sl"] if c else 0.0, "pq": p["sl"] if p else 0.0, "ct": c["tt"] if c else 0.0})
    items.sort(key=lambda x: (-x["gia"], x["ten"]))
    for x in items:  # ten chua co so (ham luong) -> them ham luong cho ro
        x["name"] = x["ten"] + (" " + x["hl"] if x["hl"] and len(x["hl"]) <= 10 and ";" not in x["hl"] and not re.search(r"\d", x["ten"]) else "")
    tc = sum(x["ct"] for x in items)
    tp = sum(e["tt"] for e in pg.values()) if pg is not None else None
    return items, tc, tp


def drug_sentence(prefix, x, m, pm, have_prev):
    u = (x["dvt"] or "").lower()
    base = f"{prefix} {x['name']} đơn giá {f0(x['gia'])} đồng"
    cq, pq = x["cq"], x["pq"]
    if cq > 0 and not have_prev:
        return f"{base} sử dụng {f0(cq)} {u}."
    if cq > 0:
        d = cq - pq
        if pq == 0:
            return f"{base} sử dụng {f0(cq)} {u}, tăng {f0(cq)} {u} so với tháng {pm} (tháng {pm} không sử dụng)."
        if d == 0:
            return f"{base} sử dụng {f0(cq)} {u}, không đổi so với tháng {pm}."
        return f"{base} sử dụng {f0(cq)} {u}, {word(d)} {f0(abs(d))} {u} so với tháng {pm}."
    if have_prev and pq > 0:
        return f"{base} không sử dụng trong tháng {m}, giảm {f0(pq)} {u} so với tháng {pm}."
    return f"{base} không sử dụng trong tháng {m}."


# ----------------------------------------------------------------------------- noi dung bao cao
def build_text(m, y, A, P, stats, pstats, watch, cur_rows, prev_rows):
    """A: phan tich thang nay; P: phan tich thang truoc (hoac None)."""
    pm = prev_period(m, y)[0]
    have = P is not None
    T = {}

    def chg(cur, prev, unit="đồng"):
        if prev is None:
            return ""
        d = cur - prev
        return f", {word(d)} so với tháng {pm}" if d == 0 else f" {word(d)} {f0(abs(d))} {unit} so với tháng {pm}"

    # --- muc 1
    if have:
        d = A["total"] - P["total"]
        s = (f"Kinh phí sử dụng thuốc tháng {m} {word(d)} so với tháng {pm}" +
             ("" if d == 0 else f" là {f0(abs(d))} đồng") + ".")
    else:
        s = f"Kinh phí sử dụng thuốc tháng {m} là {f0(A['total'])} đồng."
    st = stats or {}
    ps = pstats or {}

    def pv(k):
        return ps.get(k) if ps and k in ps else None

    def cp(k, unit="đồng"):
        return chg(st[k], pv(k), unit)

    if "noitru" in st:
        s += (f" Trong đó, kinh phí thuốc nội trú" + (f" {word(st['noitru'] - pv('noitru'))} {f0(abs(st['noitru'] - pv('noitru')))}"
              if pv("noitru") is not None else f" là {f0(st['noitru'])}") + " đồng.")
    if "ngoai_tay" in st:
        s += (" Kinh phí thuốc ngoại trú tây y" + (f" {word(st['ngoai_tay'] - pv('ngoai_tay'))} {f0(abs(st['ngoai_tay'] - pv('ngoai_tay')))}"
              if pv("ngoai_tay") is not None else f" là {f0(st['ngoai_tay'])}") + " đồng.")
    bq_tay = st.get("bq_tay") or (st["ngoai_tay"] / st["bn_tay"] if st.get("ngoai_tay") and st.get("bn_tay") else None)
    pbq_tay = pv("bq_tay") or (ps["ngoai_tay"] / ps["bn_tay"] if ps.get("ngoai_tay") and ps.get("bn_tay") else None)
    if "bn_tay" in st:
        s += f" Trong tháng {m} có {f0(st['bn_tay'])} bệnh nhân ngoại trú lãnh thuốc tây y{cp('bn_tay', 'bệnh nhân')}"
        if bq_tay:
            s += f", trung bình toa tháng {m} là {f0(bq_tay)} đồng{chg(bq_tay, pbq_tay)}"
        s += "."
    if "dongy" in st:
        s += f" Kinh phí thuốc đông y tháng {m} dùng {f0(st['dongy'])} đồng{cp('dongy')}"
        bq_d = st.get("bq_dong") or (st["dongy"] / st["bn_dong"] if st.get("bn_dong") else None)
        pbq_d = pv("bq_dong") or (ps["dongy"] / ps["bn_dong"] if ps.get("dongy") and ps.get("bn_dong") else None)
        if bq_d:
            s += f", trung bình toa {f0(bq_d)} đồng{chg(bq_d, pbq_d)}"
        s += "."
    if "bn_dong" in st:
        s += f" Tháng {m} có {f0(st['bn_dong'])} bệnh nhân ngoại trú lãnh thuốc đông y{cp('bn_dong', 'bệnh nhân')}."
    if "hs_noitru" in st:
        s += f" Đối với hồ sơ nhập viện nội trú tháng {m} có {f0(st['hs_noitru'])} hồ sơ{cp('hs_noitru', 'hồ sơ')}."
    T["item1"] = s

    # --- muc 2, 3
    for key, ven, lab in (("item2", "N", "không thiết yếu"), ("item3", "V", "quan trọng")):
        c = A["ven"][ven]["v"]
        if have:
            d = c - P["ven"][ven]["v"]
            T[key] = f"Kinh phí sử dụng thuốc {lab} tháng {m} {word(d)} so với tháng {pm}" + \
                     ("" if d == 0 else f" là {f0(abs(d))} đồng") + "."
        else:
            T[key] = f"Kinh phí sử dụng thuốc {lab} tháng {m} là {f0(c)} đồng."

    # --- cac hoat chat theo doi
    W = []
    for spec in watch:
        if not spec.get("on", True):
            continue
        items, tc, tp = watch_lines(cur_rows, prev_rows, spec, m, pm)
        e = {"spec": spec, "items": items, "tc": tc, "tp": tp}
        if spec.get("mode") == "total":
            d = None if tp is None else tc - tp
            e["text"] = (f"{spec['summary']} {f0(tc)} đồng" +
                         ("" if d is None else (f" {word(d)} so với tháng {pm}" + ("" if d == 0 else f" là {f0(abs(d))} đồng"))) + ".")
        else:
            brands = [norm(b) for b in spec.get("brand", [])]
            lines = []
            for x in items:
                if brands:
                    pre = "Thuốc biệt dược" if any(b in norm(x["ten"]) for b in brands) else "Thuốc generic"
                else:
                    pre = "Thuốc"
                lines.append(drug_sentence(pre, x, m, pm, prev_rows is not None))
            e["lines"] = lines
            if items:
                d = None if tp is None else tc - tp
                e["sum"] = (f"{spec['summary']} tháng {m} là {f0(tc)} đồng" +
                            ("" if d is None else f", {word(d)}" + ("" if d == 0 else f" {f0(abs(d))} đồng") + f" so với tháng {pm}") + ".")
                if spec.get("recommend"):
                    gen = [x for x in items if x["cq"] > 0 and not any(b in norm(x["ten"]) for b in brands)]
                    if gen:
                        ds = [f"{x['name']} đơn giá {f0(x['gia'])} đồng" for x in gen]
                        ds = ds[0] if len(ds) == 1 else ", ".join(ds[:-1]) + " và " + ds[-1]
                        e["sum"] += " " + spec["recommend"].replace("{ds}", ds)
            else:
                e["sum"] = f"Không có thuốc hoạt chất này được sử dụng trong tháng {m}."
        W.append(e)
    T["watch"] = W
    return T


# ----------------------------------------------------------------------------- Word: ham dinh dang
def _fill_table(tbl, data):
    """Ghi tung o cua cac dong du lieu co san (dong 1 tro di) - cho bang VEN/ABC/ma tran."""
    from docx.oxml.ns import qn
    for ri, row in enumerate(data):
        for tc, val in zip(tbl.rows[1 + ri]._tr.findall(qn("w:tc")), row):
            if val is not None:
                set_cell(tc, tbl, val)


# ----------------------------------------------------------------------------- Word: sinh bao cao
def make_report(out_path, m, y, A, P, T, template):
    from docx import Document
    doc = Document(str(template))
    pm = prev_period(m, y)[0]
    have = P is not None
    nm, ny = next_period(m, y)

    tb = doc.tables
    if len(tb) < 6:
        raise ValueError("Mẫu Word phải có đủ 6 bảng (tiêu đề, VEN, ABC, ma trận, AN, AV).")
    t_head, t_ven, t_abc, t_mat, t_an, t_av = tb[:6]

    # --- tieu de, ngay
    for p in t_head.rows[0].cells[1].paragraphs:
        if "ngày" in p.text and "tháng" in p.text:
            repl_group(p, r"năm\s*(\d{4})", str(ny))
            repl_group(p, r"tháng\s*[\.…\s]*(\d{1,2})", str(nm))
    p = find_par(doc, lambda t: "DANH MỤC THUỐC SỬ DỤNG" in t)
    set_par(p, f"DANH MỤC THUỐC SỬ DỤNG THÁNG {m}/{y}")
    p = find_par(doc, lambda t: t.startswith("Nhằm quản lý"))
    txt = re.sub(r"tháng\s*\d+/\d{4}", f"tháng {m}/{y}", p.text)
    set_par(p, txt)

    # --- tong
    set_par(find_par(doc, lambda t: t.startswith("- Tổng số loại thuốc")), f"- Tổng số loại thuốc sử dụng: {f0(A['n'])}")
    set_par(find_par(doc, lambda t: t.startswith("- Tổng giá trị sử dụng")), f"- Tổng giá trị sử dụng: {f0(A['total'])} đồng")

    tot = A["total"]
    # --- VEN
    rows = []
    for k in "VEN":
        rows.append([k, f0(A["ven"][k]["n"]), pct(A["ven"][k]["n"] / A["n"] * 100), f0(A["ven"][k]["v"]), pct(A["ven"][k]["v"] / tot * 100)])
    rows.append(["Tổng", f0(A["n"]), "100%", f0(tot), "100%"])
    _fill_table(t_ven, [r[0:] for r in rows])
    top = max("VEN", key=lambda k: A["ven"][k]["v"])
    set_par(find_par(doc, lambda t: t.startswith("- Nhóm thuốc") and "nhiều nhất" in t),
            f"- Nhóm thuốc {top} chiếm tỷ lệ nhiều nhất {pct(A['ven'][top]['v'] / tot * 100)}")
    nsh = A["ven"]["N"]["v"] / tot * 100
    if have:
        dsh = nsh - P["ven"]["N"]["v"] / P["total"] * 100
        tail = f" {word(round(dsh, 2))}" + ("" if round(dsh, 2) == 0 else f" {pct(abs(dsh))}") + f" so với tháng {pm}."
    else:
        tail = "."
    set_par(find_par(doc, lambda t: t.startswith("- Nhóm thuốc N")), f"- Nhóm thuốc N chiếm tỷ lệ {pct(nsh)}{tail}")

    # --- ABC
    rows = []
    for k in "ABC":
        rows.append([k, f0(A["abc"][k]["n"]), pct(A["abc"][k]["n"] / A["n"] * 100), f0(A["abc"][k]["v"]), pct(A["abc"][k]["v"] / tot * 100)])
    rows.append(["Tổng", f0(A["n"]), "100%", f0(tot), "100%"])
    _fill_table(t_abc, rows)
    for k, lab in (("A", "Thuốc hạng A chiếm tỷ lệ {} giá trị sử dụng. "), ("B", "Thuốc hạng B chiếm {} giá trị sử dụng."),
                   ("C", "Thuốc hạng C chiếm {} giá trị sử dụng.")):
        set_par(find_par(doc, lambda t, k=k: t.startswith(f"Thuốc hạng {k} chiếm")),
                "\t" + lab.format(pct(A["abc"][k]["v"] / tot * 100)))

    assessment = find_par(doc, lambda t: 'Phù hợp với Thông tư 21' in t)
    checks = abc_rule_warnings(A)
    set_par(assessment, ('Cần kiểm tra lại phân loại ABC: ' + ' '.join(checks)) if checks else
            'Các tỷ lệ ABC nằm trong khoảng kiểm tra đã cấu hình.')

    # --- ma tran
    rows = []
    for k in ("I", "II", "III"):
        rows.append([k, f0(A["mat"][k]["n"]), pct(A["mat"][k]["n"] / A["n"] * 100), f0(A["mat"][k]["v"]), pct(A["mat"][k]["v"] / tot * 100)])
    rows.append(["Tổng", f0(A["n"]), "100%", f0(tot), "100%"])
    _fill_table(t_mat, rows)
    for k in ("I", "II", "III"):
        pre = {"I": "Nhóm I:", "II": "Nhóm II:", "III": "Nhóm III:"}[k]
        set_par(find_par(doc, lambda t, pre=pre: t.startswith(pre)),
                f"Nhóm {k}: Có tỷ lệ về số lượng thuốc {pct(A['mat'][k]['n'] / A['n'] * 100)}, "
                f"tỷ lệ về giá trị {pct(A['mat'][k]['v'] / tot * 100)}.")
    ph = find_par(doc, lambda t: t.startswith("Tỷ lệ hợp lý"))
    hl = (A["mat"]["I"]["v"] + A["mat"]["II"]["v"]) / tot * 100
    set_par(ph, "\t\t" + re.sub(r"là\s*[\d.,]+%", f"là {pct(hl)}", ph.text.strip()))

    # --- hang A: AN / AV
    pa = find_par(doc, lambda t: t.startswith("Phân tích thuốc hạng A"))
    set_par(pa, [("Phân tích thuốc hạng A theo ABC/VEN:", {"b": True}),
                 (f" Hạng A có tổng cộng {f0(A['abc']['A']['n'])} thuốc, trong đó có:", {"b": False})])

    def a_block(par_pred, tbl, lst, label_fn, key):
        par = find_par(doc, par_pred)
        v = sum(r["tt"] for r in lst)
        pv_ = None
        if have:
            pv_ = sum(r["tt"] for r in P[key])
        sfx = ""
        if pv_ is not None:
            d = v - pv_
            sfx = f", {word(d)}" + ("" if d == 0 else f" {f0(abs(d))} đồng") + f" so với tháng {pm}"
        if lst:
            set_par(par, "- " + label_fn(len(lst), v) + sfx + ".")
            fill_rows(tbl, [[str(i), r["ten"], r["hc"], r["dvt"], f0(r["gia"]), f0(r["sl"]), f0(r["tt"])] for i, r in enumerate(lst, 1)])
        else:
            set_par(par, "- " + label_fn(0, 0) + (f" (tháng {pm}: {f0(pv_)} đồng)" if pv_ else "") + ".")
            tbl._tbl.getparent().remove(tbl._tbl)

    a_block(lambda t: t.startswith("- ") and "thuốc không thiết yếu" in t, t_an, A["an"],
            lambda n, v: (f"{f0(n)} thuốc không thiết yếu (nhóm AN), tổng giá trị {f0(v)} đồng" if n
                          else "Không có thuốc không thiết yếu (nhóm AN) trong hạng A"), "an")
    a_block(lambda t: t.startswith("- ") and "thuốc quan trọng AV" in t, t_av, A["av"],
            lambda n, v: (f"{f0(n)} thuốc quan trọng AV chiếm tỉ lệ cao {f0(v)} đồng" if n
                          else "Không có thuốc quan trọng (nhóm AV) trong hạng A"), "av")

    # --- ket luan
    head = find_par(doc, lambda t: "Kết luận và kiến nghị" in t)
    sign = find_par(doc, lambda t: "GIÁM ĐỐC" in t)
    p_item = find_par(doc, lambda t: t.startswith("1. Kinh phí"))
    p_tot = find_par(doc, lambda t: t.startswith("4. Kháng sinh nhóm Colistin"))
    p_h = find_par(doc, lambda t: t.startswith("6. Tình hình"))
    p_sub = find_par(doc, lambda t: t.startswith("Hoạt chất Meropenem"))
    p_b = find_par(doc, lambda t: t.startswith("Thuốc biệt dược Meronem"))
    p_s = find_par(doc, lambda t: t.startswith("Tình hình sử dụng kháng sinh hoạt chất"))
    protos = {k: copy.deepcopy(v._p) for k, v in (("item", p_item), ("tot", p_tot), ("h", p_h), ("sub", p_sub), ("b", p_b), ("s", p_s))}
    parent = head._parent
    # xoa phan cu giua tieu de ket luan va chu ky
    el = head._p.getnext()
    while el is not None and el is not sign._p:
        nxt = el.getnext()
        el.getparent().remove(el)
        el = nxt
    from docx.text.paragraph import Paragraph

    cur = head._p

    def add(kind, text):
        nonlocal cur
        e = copy.deepcopy(protos[kind])
        cur.addnext(e)
        set_par(Paragraph(e, parent), text)
        cur = e

    add("item", "1. " + T["item1"])
    add("item", "2. " + T["item2"])
    add("item", "3. " + T["item3"])
    n = 4
    for w in T["watch"]:
        spec = w["spec"]
        if spec.get("mode") == "total":
            add("tot", f"{n}. {w['text']}")
        else:
            add("h", f"{n}. {spec['title']}")
            if spec.get("sub"):
                add("sub", spec["sub"])
            for ln in w["lines"]:
                add("b", ln)
            add("s", w["sum"])
        n += 1
    e = copy.deepcopy(protos["s"])
    cur.addnext(e)
    set_par(Paragraph(e, parent), "")
    out_path = Path(out_path)
    save_document(doc,out_path)


# ----------------------------------------------------------------------------- quy trinh tong
def generate(cur_path, month, year, prev_path=None, mode="calc", a_pct=78.0, b_pct=95.0,
             stats=None, pstats=None, watch=None, sheet=None, prev_sheet=None):
    """Doc Excel -> phan tich -> luu lich su -> sinh Word. Tra ve dict ket qua."""
    validate_period(month, year)
    pm, py = prev_period(month, year)
    rows, info = read_drug_file(cur_path, sheet)
    method = classify(rows, mode == "file", a_pct, b_pct)
    A = analyze(rows)
    warnings = list(info["warnings"])

    # thang truoc: file moi tai len > lich su
    prev_rows = P = None
    prev_src = None
    if prev_path:
        prows, pinfo = read_drug_file(prev_path, prev_sheet)
        classify(prows, pinfo.get('has_class', False), a_pct, b_pct)
        prev_rows, prev_src = prows, "file tải lên"
        warnings += ["Tháng trước: " + w for w in pinfo["warnings"]]
    else:
        h = load_period(pm, py)
        if h and h.get("rows"):
            prev_rows, prev_src = h["rows"], f"lịch sử tháng {pm}/{py}"
            for r in prev_rows:
                r.setdefault("nhom", nhom_of(r.get("hang", "C"), r.get("ven", "E")))
    if prev_rows is not None:
        P = analyze(prev_rows)
    else:
        warnings.append(f"Chưa có dữ liệu tháng {pm}/{py}: các câu so sánh với tháng trước được bỏ qua. "
                        "Hãy chọn file tháng trước để có so sánh.")

    # so lieu kinh phi
    stats = {k: num(v) for k, v in (stats or {}).items() if v not in (None, "")}
    pstats = {k: num(v) for k, v in (pstats or {}).items() if v not in (None, "")}
    if not pstats:
        h = load_period(pm, py)
        if h and h.get("stats"):
            pstats = h["stats"]
    if not stats:
        warnings.append("Chưa nhập số liệu kinh phí nội/ngoại trú: mục 1 của phần Kết luận chỉ nêu tổng kinh phí.")

    W = watch if watch is not None else load_watch()
    T = build_text(month, year, A, P, stats, pstats, W, rows, prev_rows)
    template = CFG["root"] / "ABC_VEN" / "Mau_bao_cao_ABC_VEN.docx"
    if not template.exists():
        raise FileNotFoundError(f"Không thấy file mẫu Word: {template}")
    name = f"Phan_tich_ABC_VEN_thang_{month}_nam_{year}.docx"
    out = data_directory(CFG) / "Bao_cao" / name
    make_report(out, month, year, A, P, T, template)
    # Commit history only after the report was successfully written.
    if prev_path:
        save_period(pm, py, rows=prev_rows)
    save_period(month, year, rows=rows, stats=stats, method=method)

    # kiem tra nhanh
    warnings.extend(abc_rule_warnings(A))
    for e in T["watch"]:
        if not e["items"] and e["spec"].get("on", True):
            warnings.append(f"Hoạt chất theo dõi '{e['spec']['kw'][0]}' không có dòng nào trong file Excel.")
    summary = {
        "n": A["n"], "total": A["total"], "method": method, "sheet": info["sheet"], "prev_src": prev_src,
        "ven": {k: {"n": A["ven"][k]["n"], "v": A["ven"][k]["v"], "pv": A["ven"][k]["v"] / A["total"] * 100} for k in "VEN"},
        "abc": {k: {"n": A["abc"][k]["n"], "v": A["abc"][k]["v"], "pv": A["abc"][k]["v"] / A["total"] * 100, "pn": A["abc"][k]["n"] / A["n"] * 100} for k in "ABC"},
        "mat": {k: {"n": A["mat"][k]["n"], "v": A["mat"][k]["v"], "pv": A["mat"][k]["v"] / A["total"] * 100} for k in ("I", "II", "III")},
        "an": len(A["an"]), "av": len(A["av"]),
    }
    return {"ok": True, "name": name, "path": str(out), "summary": summary, "warnings": warnings}


# ----------------------------------------------------------------------------- Xuat Excel ABC/VEN thang

def export_month_xlsx(rows, month, year, warnings=None, reviews=None):
    """Luu bang thuoc da gop/phan hang va chi tiet canh bao de doi chieu."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb=Workbook(); ws=wb.active; ws.title='Du_lieu_ABC_VEN'
    ws.append(['Mã dược','Tên thuốc','Hoạt chất','Hàm lượng','Quy cách','VEN','ĐVT',
               'Đơn giá bình quân','Số lượng xuất','Thành tiền','Phân hạng ABC','Nhóm ABC/VEN'])
    for r in rows:
        ws.append([r.get(k,'') for k in ('ma','ten','hc','hl','qc','ven','dvt','gia','sl','tt','hang','nhom')])
    ws.freeze_panes='C2'; ws.auto_filter.ref=f'A1:L{len(rows)+1}'
    for col,width in {'A':17,'B':47,'C':36,'D':26,'E':37,'F':10,'G':12,'H':22,'I':19,'J':23,'K':19,'L':20}.items():
        ws.column_dimensions[col].width=width
    for r in ws.iter_rows(min_row=2,min_col=8,max_col=10):
        for cell in r:cell.number_format='#,##0.00' if cell.column==8 else '#,##0.##'
    for c in ws[1]:
        c.fill=PatternFill('solid',fgColor='17365D');c.font=Font(color='FFFFFF',bold=True)
        c.alignment=Alignment(wrap_text=True)
    ws.row_dimensions[1].height=31

    a=analyze(rows); summary=wb.create_sheet('Tong_hop')
    summary.append(['BÁO CÁO ABC/VEN',f'Tháng {month:02d}/{year}'])
    summary.append(['Tổng số mặt hàng',a['n']]);summary.append(['Tổng thành tiền',a['total']])
    summary.append(['Hạng ABC','Số mặt hàng','% mặt hàng','Giá trị (đồng)','% giá trị','Đánh giá'])
    for label in 'ABC':
        s=a['abc'][label]; pc=s['n']/a['n']*100 if a['n'] else 0; pv=s['v']/a['total']*100 if a['total'] else 0
        check=('Đạt' if ((75<=pv<=80 if label=='A' else 15<=pv<=20) and 10<=pc<=20) else 'Cần kiểm tra') if label!='C' else 'Còn lại'
        summary.append([label,s['n'],pc,s['v'],pv,check])
    summary.append([]);summary.append(['Phân loại VEN','Số mặt hàng','Giá trị (đồng)'])
    for label in 'VEN':summary.append([label,a['ven'][label]['n'],a['ven'][label]['v']])
    summary.append([]);summary.append(['Nhóm ABC/VEN','Số mặt hàng','Giá trị (đồng)'])
    for label in ('I','II','III'):summary.append([label,a['mat'][label]['n'],a['mat'][label]['v']])
    for col,width in {'A':30,'B':22,'C':20,'D':24,'E':18,'F':21}.items():summary.column_dimensions[col].width=width
    for idx in (1,4,9,14):
        for c in summary[idx]:c.font=Font(bold=True,color='17365D')
    for row in (5,6,7):
        summary.cell(row,3).number_format='0.00"%"';summary.cell(row,5).number_format='0.00"%"'
        summary.cell(row,4).number_format='#,##0.##'
    summary.freeze_panes='A4'

    rev=wb.create_sheet('Canh_bao_can_kiem_tra')
    rev.append(['Nguồn','Dòng Excel','Mã dược','Tên thuốc','Hàm lượng','Quy cách','Trạng thái','Ghi chú'])
    for r in reviews or []:
        rev.append([r.get('source',''),r.get('row',''),r.get('ma',''),r.get('ten',''),r.get('hl',''),r.get('qc',''),r.get('status',''),r.get('note','')])
    if warnings:
        rev.append([]);rev.append(['CẢNH BÁO CHUNG'])
        for w in warnings:rev.append([w])
    for c in rev[1]:c.fill=PatternFill('solid',fgColor='9C5700');c.font=Font(color='FFFFFF',bold=True)
    for col,width in {'A':24,'B':15,'C':20,'D':45,'E':28,'F':36,'G':32,'H':85}.items():rev.column_dimensions[col].width=width
    rev.freeze_panes='D2';rev.auto_filter.ref=f'A1:H{1+len(reviews or [])}'
    name=f'Du_lieu_ABC_VEN_thang_{month:02d}_nam_{year}.xlsx'
    path=data_directory(CFG)/'Bao_cao'/name
    path.parent.mkdir(parents=True,exist_ok=True)
    save_data_workbook(wb, path)
    return name

# ----------------------------------------------------------------------------- so sanh 2 ky tu file Excel phan mem da xuat

def compare_month_rows(current, previous):
    """Doi chieu theo Ten + Ham luong + Quy cach, khong nhap nhang hai quy cach."""
    variants={}
    for r in current+previous:
        identity=tuple(norm(r.get(k,'')) for k in ('ten','hl','qc'))
        variants.setdefault(identity,set()).add((r.get('ven',''),norm(r.get('dvt',''))))
    def keyed(items):
        result={}
        for r in items:
            identity=tuple(norm(r.get(k,'')) for k in ('ten','hl','qc'))
            uncertain=not r.get('qc') or not r.get('hl') or len(variants[identity])>1
            key=identity+(str(r.get('ma','')).strip().upper() if uncertain else '',norm(r.get('dvt','')))
            if not key[0]:continue
            if key not in result:
                result[key]={'ma':r.get('ma',''),'ten':r.get('ten',''),'hl':r.get('hl',''),'qc':r.get('qc',''),
                             'sl':0.0,'tt':0.0,'hang':r.get('hang',''), 'ven':r.get('ven','')}
            result[key]['sl']+=num(r.get('sl'))
            result[key]['tt']+=num(r.get('tt'))
        return result
    c=keyed(current);p=keyed(previous)
    # File xuất bản cũ có thể thiếu Quy cách: không coi biến thể không khớp
    # là thuốc mới / ngừng dùng khi cùng tên + hàm lượng tồn tại phía kia.
    old_names_without_qc={(k[0],k[1]) for k in p if not k[2]}
    new_names_without_qc={(k[0],k[1]) for k in c if not k[2]}
    details=[]
    for key in sorted(set(c)|set(p)):
        a=c.get(key);b=p.get(key)
        v=a or b
        cur_cost=a['tt'] if a else 0; prev_cost=b['tt'] if b else 0
        cur_qty=a['sl'] if a else 0; prev_qty=b['sl'] if b else 0
        old_group=b['hang'] if b else ''
        new_group=a['hang'] if a else ''
        if not b and (key[0],key[1]) in old_names_without_qc:
            status='Chưa đối chiếu: tháng trước thiếu quy cách'
        elif not a and (key[0],key[1]) in new_names_without_qc:
            status='Chưa đối chiếu: tháng này thiếu quy cách'
        elif not b:status='Thuốc mới'
        elif not a:status='Không còn sử dụng'
        elif old_group!=new_group:status=f'Chuyển {old_group or "?"} → {new_group or "?"}'
        else:status='Đang sử dụng'
        details.append({'ma':v['ma'],'ten':v['ten'],'hl':v['hl'],'qc':v['qc'],
                        'prev_sl':prev_qty,'cur_sl':cur_qty,
                        'prev_price':prev_cost/prev_qty if prev_qty else 0,
                        'cur_price':cur_cost/cur_qty if cur_qty else 0,
                        'prev_tt':prev_cost,'cur_tt':cur_cost,'diff':cur_cost-prev_cost,
                        'change_pct':((cur_cost/prev_cost-1)*100 if prev_cost else None),
                        'prev_abc':old_group,'cur_abc':new_group,
                        'prev_ven':b['ven'] if b else '', 'cur_ven':a['ven'] if a else '',
                        'status':status})
    details.sort(key=lambda x:-abs(x['diff']))
    old=sum(x['tt'] for x in p.values());new=sum(x['tt'] for x in c.values())
    return {'prev_n':len(p),'cur_n':len(c),'prev_total':old,'cur_total':new,
            'delta':new-old,'delta_pct':((new/old-1)*100 if old else None),
            'uncertain_pairs':sum(x['status'].startswith('Chưa đối chiếu:') for x in details),
            'new_drugs':sum(x['status']=='Thuốc mới' for x in details),
            'stopped_drugs':sum(x['status']=='Không còn sử dụng' for x in details),
            'abc_changes':sum(bool(x['prev_abc'] and x['cur_abc'] and x['prev_abc']!=x['cur_abc']) for x in details),
            'details':details}


def export_compare_xlsx(cmp, month, year):
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    wb=Workbook();ws=wb.active;ws.title='So_sanh_hai_thang'
    ws.append(['Mã dược','Tên thuốc','Hàm lượng','Quy cách','SL tháng trước','SL tháng này',
               'Đơn giá tháng trước','Đơn giá tháng này','Tiền tháng trước','Tiền tháng này',
               'Chênh lệch tiền','% thay đổi','ABC trước','ABC này','VEN trước','VEN này','Tình trạng'])
    for r in cmp['details']:
        ws.append([r[k] for k in ('ma','ten','hl','qc','prev_sl','cur_sl','prev_price','cur_price',
                                  'prev_tt','cur_tt','diff','change_pct','prev_abc','cur_abc',
                                  'prev_ven','cur_ven','status')])
    ws.freeze_panes='D2';ws.auto_filter.ref=f'A1:Q{ws.max_row}'
    for c,w in {'A':18,'B':47,'C':23,'D':37,'E':18,'F':18,'G':22,'H':22,'I':22,'J':22,'K':22,'L':16,'M':13,'N':13,'O':13,'P':13,'Q':23}.items():ws.column_dimensions[c].width=w
    for row in ws.iter_rows(min_row=2):
        for cell in row[4:12]:cell.number_format='#,##0.00' if cell.column in (7,8,12) else '#,##0.##'
    for c in ws[1]:c.fill=PatternFill('solid',fgColor='17365D');c.font=Font(color='FFFFFF',bold=True);c.alignment=Alignment(wrap_text=True)
    ws.row_dimensions[1].height=32
    summary=wb.create_sheet('Tong_hop_so_sanh',0)
    pm,py=prev_period(month,year)
    summary.append(['Đối chiếu ABC/VEN',f'Tháng {pm:02d}/{py} → {month:02d}/{year}'])
    for label,key in [('Mặt hàng tháng trước','prev_n'),('Mặt hàng tháng này','cur_n'),('Tiền tháng trước','prev_total'),('Tiền tháng này','cur_total'),('Chênh lệch tiền','delta'),('% thay đổi','delta_pct'),('Thuốc mới','new_drugs'),('Thuốc không còn dùng','stopped_drugs'),('Chưa đối chiếu quy cách','uncertain_pairs'),('Thuốc đổi nhóm ABC','abc_changes')]:summary.append([label,cmp[key]])
    summary.column_dimensions['A'].width=32;summary.column_dimensions['B'].width=29
    for c in summary[1]:c.font=Font(bold=True,color='17365D')
    summary['B7'].number_format='0.00"%"'
    name=f'So_sanh_ABC_VEN_thang_{month:02d}_nam_{year}.xlsx'
    out=data_directory(CFG)/'Bao_cao'/name;out.parent.mkdir(parents=True,exist_ok=True);save_data_workbook(wb,out)
    return name

# ----------------------------------------------------------------------------- Flask
def make_blueprint():
    from flask import Blueprint, jsonify, request
    bp = Blueprint("abcven", __name__)
    file_routes(bp, "abc", lambda: data_directory(CFG) / "Bao_cao", (".docx", ".xlsx"))

    @bp.get("/api/abc/state")
    def state():
        today = datetime.date.today()
        m, y = prev_period(today.month, today.year)
        return jsonify(month=m, year=y, watch=load_watch(), fields=[{"key": k, "label": l} for k, l in STAT_FIELDS],
                       template=(CFG["root"] / "ABC_VEN" / "Mau_bao_cao_ABC_VEN.docx").exists())

    @bp.get("/api/abc/history")
    def history():
        m, y = int(request.args.get("month", 1)), int(request.args.get("year", 2000))
        pm, py = prev_period(m, y)
        h, c = load_period(pm, py) or {}, load_period(m, y) or {}
        return jsonify(prev_has_rows=bool(h.get("rows")), prev_stats=h.get("stats") or {}, cur_stats=c.get("stats") or {}, pm=pm, py=py)

    @bp.post("/api/abc/inspect")
    @safe
    def inspect():
        with upload("file") as p:
            _, info = read_drug_file(p)
        return jsonify(ok=True, **{k: info[k] for k in ("sheet", "rows", "total", "has_class", "warnings")})

    @bp.post("/api/abc/inspect-four")
    @safe
    def inspect_four():
        from contextlib import ExitStack
        with ExitStack() as stack:
            paths=[stack.enter_context(upload(k)) for k in ('khu','bhyt','noi','dm')]
            if any(p is None for p in paths):raise ValueError('Cần chọn đủ ba file xuất và danh mục dược.')
            _,info=prepare_four_files(*paths)
        return jsonify(ok=True,**info)

    @bp.post("/api/abc/generate-four")
    @guarded(_LOCK,('docx',),perm='Không ghi được file Word.')
    def generate_four():
        from contextlib import ExitStack
        o=json.loads(request.form.get('opts','{}'))
        with ExitStack() as stack:
            paths=[stack.enter_context(upload(k)) for k in ('khu','bhyt','noi','dm')]
            if any(p is None for p in paths):return jsonify(ok=False,msg='Cần chọn đủ bốn file đầu vào.')
            rows,info=prepare_four_files(*paths)
            # Existing report generation still expects an Excel workbook.
            import tempfile,openpyxl
            with tempfile.TemporaryDirectory(prefix='pd_abc4_') as td:
                converted=Path(td)/'abc_ven_chuan.xlsx'
                wb=openpyxl.Workbook();ws=wb.active;ws.title='ABC_VEN'
                ws.append(['Mã dược','Tên thuốc','Hoạt chất','Hàm lượng','Quy cách','VEN','ĐVT','Đơn giá','Số lượng','Thành tiền'])
                for r in rows:ws.append([r[k] for k in ('ma','ten','hc','hl','qc','ven','dvt','gia','sl','tt')])
                save_data_workbook(wb,converted)
                with upload('prev') as prev:
                    res=generate(converted,int(o['month']),int(o['year']),prev,o.get('mode','calc'),
                                 float(o.get('a',78)),float(o.get('b',95)),o.get('stats'),o.get('pstats'),
                                 watch=(save_watch(o['watch']) if o.get('watch') else None))
        res.pop('path',None)
        res.setdefault('warnings',[]).extend(info['warnings'])
        res['reviews']=info['reviews']
        return jsonify(res)

    @bp.post('/api/abc/export-month')
    @guarded(_LOCK, ('openpyxl',), perm='Không ghi được file Excel. Hãy đóng file đang mở rồi thử lại.')
    def export_month():
        from contextlib import ExitStack
        o=json.loads(request.form.get('opts','{}'))
        month=int(o.get('month',0));year=int(o.get('year',0))
        if not 1<=month<=12 or not 2000<=year<=2100:
            return jsonify(ok=False,msg='Tháng hoặc năm báo cáo không hợp lệ.')
        mode=o.get('mode','calc'); ap=float(o.get('a',78));bpct=float(o.get('b',95))
        reviews=[]
        with ExitStack() as stack:
            if request.form.get('four')=='1':
                paths=[stack.enter_context(upload(k)) for k in ('khu','bhyt','noi','dm')]
                if any(p is None for p in paths):return jsonify(ok=False,msg='Hãy chọn đủ 4 file đầu vào.')
                rows,info=prepare_four_files(*paths)
                reviews=info.get('reviews',[])
            else:
                p=stack.enter_context(upload('cur'))
                if p is None:return jsonify(ok=False,msg='Hãy chọn file ABC/VEN của tháng.')
                rows,info=read_drug_file(p)
        method=classify(rows,mode=='file',ap,bpct)
        warnings=list(info.get('warnings',[]))+abc_rule_warnings(analyze(rows))
        name=export_month_xlsx(rows,month,year,warnings,reviews)
        return jsonify(ok=True,name=name,rows=len(rows),warnings=warnings,reviews=len(reviews),method=method)

    @bp.post('/api/abc/compare-month')
    @guarded(_LOCK, ('openpyxl',), perm='Không ghi được file so sánh Excel.')
    def compare_month():
        from contextlib import ExitStack
        o=json.loads(request.form.get('opts','{}'))
        m=int(o.get('month',0));y=int(o.get('year',0))
        if not 1<=m<=12 or not 2000<=y<=2100:
            return jsonify(ok=False,msg='Chọn tháng/năm báo cáo hợp lệ.')
        with ExitStack() as stack:
            prev=stack.enter_context(upload('prev'))
            if not prev:return jsonify(ok=False,msg='Hãy chọn Excel tháng trước do PharmaDesk xuất.')
            prev_rows,prev_info=read_drug_file(prev)
            if request.form.get('four')=='1':
                paths=[stack.enter_context(upload(k)) for k in ('khu','bhyt','noi','dm')]
                if any(p is None for p in paths):return jsonify(ok=False,msg='Hãy chọn đủ 4 file của tháng hiện tại.')
                current,info=prepare_four_files(*paths)
            else:
                cur=stack.enter_context(upload('cur'))
                if not cur:return jsonify(ok=False,msg='Hãy chọn Excel tháng hiện tại.')
                current,info=read_drug_file(cur)
        classify(current,o.get('mode')=='file',float(o.get('a',78)),float(o.get('b',95)))
        # Giữ ABC của file tháng trước đã xuất; nếu file không có ABC thì tự phân loại.
        classify(prev_rows,prev_info.get('has_class',False),float(o.get('a',78)),float(o.get('b',95)))
        result=compare_month_rows(current,prev_rows)
        if any(not r.get('qc') for r in prev_rows):
            prev_info.setdefault('warnings',[]).append('File tháng trước có thuốc thiếu cột Quy cách: không tự ghép với thuốc có quy cách khác; hãy xuất lại file tháng cũ bằng bản cập nhật nếu còn 4 file nguồn.')
        name=export_compare_xlsx(result,m,y)
        return jsonify(ok=True,name=name,summary={k:v for k,v in result.items() if k!='details'},
                       top=result['details'][:15], warnings=info.get('warnings',[])+prev_info.get('warnings',[]))

    @bp.post("/api/abc/parse-stats")
    @safe
    def pstats():
        with upload("file") as p:
            r = parse_stats(p, int(request.form.get("month", 1)))
        if not r["cur"] and not r["prev"]:
            return jsonify(ok=False, msg="Không nhận ra bảng kinh phí (cần cột 'Tháng N' và các dòng Kinh phí thuốc nội trú/ngoại trú...).")
        return jsonify(ok=True, **r)

    @bp.post("/api/abc/watch")
    @safe
    def watch():
        d = request.get_json(silent=True) or {}
        if d.get("reset"):
            (data_directory(CFG) / "hoat_chat_theo_doi.json").unlink(missing_ok=True)
            return jsonify(ok=True, watch=load_watch())
        return jsonify(ok=True, watch=save_watch(d.get("watch", [])))

    @bp.post("/api/abc/generate")
    @guarded(_LOCK, ("docx",), perm="Không ghi được file Word. Nếu bạn đang mở file báo cáo cũ trong Word thì hãy đóng lại rồi thử lại.")
    def gen():
        o = json.loads(request.form.get("opts", "{}"))
        with upload("cur") as cur, upload("prev") as prev:
            if not cur:
                return jsonify(ok=False, msg="Chưa chọn file Excel ABC/VEN của tháng báo cáo.")
            res = generate(cur, int(o["month"]), int(o["year"]), prev, o.get("mode", "calc"), float(o.get("a", 78)),
                           float(o.get("b", 95)), o.get("stats"), o.get("pstats"),
                           watch=(save_watch(o["watch"]) if o.get("watch") else None))
        res.pop("path", None)
        return jsonify(res)

    return bp
