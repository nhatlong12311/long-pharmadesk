import os
import pandas as pd
from pathlib import Path
from collections import defaultdict
from copy import copy
from functools import lru_cache
from itertools import groupby
import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.worksheet.pagebreak import ColBreak, RowBreak
import math
import re
import unicodedata
import time
import tempfile
from PIL import ImageFont
from datetime import datetime

# Optional job-local inputs; normal merge keeps its existing defaults.
JOB = globals().get("MERGE_JOB", {})
ROOT = Path(JOB.get("root", Path(__file__).parent))
MODE = JOB.get("mode", os.environ.get("GOP_MODE"))
IS_TEST = bool(JOB.get("test"))
PROFILE_DIR = Path(JOB.get("log_dir", ROOT / "Logs"))
PROFILE_DIR.mkdir(exist_ok=True)
PROFILE_LOG = PROFILE_DIR / "Tong_hop_toc_do.log"
_PROFILE_T0 = time.perf_counter()

def profile_event(stage, detail=""):
    elapsed = time.perf_counter() - _PROFILE_T0
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | +{elapsed:8.2f}s | {stage} | {detail}"
    try:
        with PROFILE_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print("[TIME] " + line, flush=True)

try:
    PROFILE_LOG.write_text(
        f"PHARMA DESK - THOI GIAN GOP | {datetime.now():%Y-%m-%d %H:%M:%S}\n",
        encoding="utf-8"
    )
except OSError:
    pass

TEMPLATE = ROOT / "Mau tong.xlsx"
SOURCE_DIR = Path(JOB.get("source_dir", ROOT / "Excel_xuat"))
OUTPUT = ROOT / "Ket_qua_in.xlsx"

# Tim file Excel vua duoc xuat tu cac phieu RPT
files = sorted([p for p in SOURCE_DIR.glob("*") if p.is_file() and p.suffix.lower() in (".xls", ".xlsx") and not p.name.startswith("~$")])
profile_event("TAC_VU", "BOI_HOAN_TU_TRUC" if MODE == "boi" else "GOP_PHIEU_NGAY_THUONG")
profile_event("BAT_DAU_DOC_EXCEL", f"So file={len(files)}")
if not files:
    raise RuntimeError(f"Khong tim thay file Excel trong thu muc: {SOURCE_DIR}")

def norm_header(value):
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()

def find_header_row(raw):
    # Quet cac dong dau file, tim dong co ca cot ma va ten thuoc
    for idx in range(min(len(raw), 60)):
        vals = [norm_header(v) for v in raw.iloc[idx].tolist()]
        has_code = any(v in ("ma", "ma thuoc", "ma duoc", "code") for v in vals)
        has_name = any(("ten duoc" in v or "ten thuoc" in v) for v in vals)
        if has_code and has_name:
            return idx
    return None

def is_blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() == ""


def drug_key(value):
    return "" if is_blank(value) else norm_header(value).replace("đ", "d")


# Keep dosage units in the name key, while treating "375 mg" and "375mg" alike.
DOSE_UNIT = r"(?:mcg|mg|µg|μg|ug|g|kg|ml|l|iu|ui|%)"
SIMPLE_STRENGTH = re.compile(rf"(?P<amount>\d+(?:[.,]\d+)?)\s*(?:{DOSE_UNIT})?$")


def normalize_dose_spacing(value):
    return re.sub(rf"(?<=\d)\s+(?={DOSE_UNIT}(?!\w))", "", value)


def drug_name_key(value):
    return normalize_dose_spacing(drug_key(str(value).split("(", 1)[0]))


def drug_name_variants(name, strength):
    name_key = drug_name_key(name)
    yield name_key
    strength_key = normalize_dose_spacing(drug_key(strength))
    if not strength_key:
        return
    combined = name_key if name_key.endswith(" " + strength_key) else f"{name_key} {strength_key}"
    yield combined
    # Accept missing units only for a single strength; any conflicting groups
    # still need a unique match from the existing ingredient fallback.
    simple = SIMPLE_STRENGTH.fullmatch(strength_key)
    if simple:
        yield combined.removesuffix(strength_key) + simple["amount"]


def bold_characters(cell):
    value = cell.value
    if isinstance(value, CellRichText):
        for part in value:
            bold = bool(part.font.b) if isinstance(part, TextBlock) else bool(cell.font.b)
            yield from ((char, bold) for char in str(part))
    else:
        yield from ((char, bool(cell.font.b)) for char in str(value))


def catalog_display_name(name_cell, strength_cell):
    name = str(name_cell.value)
    characters = list(bold_characters(name_cell))
    characters = characters[len(name) - len(name.lstrip()):len(name.rstrip())]
    if not is_blank(strength_cell.value):
        strength = str(strength_cell.value)
        strength_chars = list(bold_characters(strength_cell))
        strength_chars = strength_chars[len(strength) - len(strength.lstrip()):len(strength.rstrip())]
        strength_key = normalize_dose_spacing(drug_key(strength))
        if not normalize_dose_spacing(drug_key(name)).endswith(" " + strength_key):
            characters.append((" ", False))
            characters.extend(strength_chars)
        else:
            # The name already includes the strength. Apply the bold flags to
            # its existing suffix, even when spacing around the unit differs.
            positions = (i for i in reversed(range(len(characters))) if not characters[i][0].isspace())
            for i, (_, bold) in zip(positions, (pair for pair in reversed(strength_chars) if not pair[0].isspace())):
                if bold:
                    characters[i] = (characters[i][0], True)
    if not any(bold for _, bold in characters):
        return "".join(char for char, _ in characters)
    runs = []
    for bold, chars in groupby(characters, key=lambda pair: pair[1]):
        text = "".join(char for char, _ in chars)
        if not text.strip() and runs:
            # openpyxl omits xml:space on a run made entirely of whitespace.
            # Keep the original spaces on the preceding visible text.
            previous = runs[-1]
            if isinstance(previous, TextBlock):
                previous.text += text
            else:
                runs[-1] += text
        else:
            runs.append(TextBlock(InlineFont(b=True), text) if bold else text)
    return CellRichText(runs)


def write_drug_name(cell, name):
    if isinstance(name, CellRichText):
        # Excel can give inline text its default size when the run omits it.
        # Set an explicit, common font for the name and highlighted strength.
        font = cell.font
        name = CellRichText([
            TextBlock(
                InlineFont(rFont=font.name, sz=font.sz or 11,
                           b=part.font.b if isinstance(part, TextBlock) else font.b),
                str(part),
            )
            for part in name
        ])
    cell.value = name


def infer_group(names, ingredients, groups_by_name, groups_by_ingredient):
    name_groups = set()
    for name in names:
        name_groups.update(groups_by_name.get(drug_name_key(name), ()))
    if len(name_groups) == 1:
        return next(iter(name_groups)), "tên thuốc"

    # Some exports provide an ingredient column, others put it in parentheses
    # or use the ingredient itself as the product name. Match whole values only.
    ingredient_keys = {drug_key(value) for value in ingredients}
    for name in names:
        ingredient_keys.add(drug_key(name))
        ingredient_keys.update(drug_key(value) for value in re.findall(r"\(([^()]*)\)", str(name)))
    ingredient_groups = set()
    for key in ingredient_keys:
        ingredient_groups.update(groups_by_ingredient.get(key, ()))
    if name_groups:
        ingredient_groups &= name_groups
    if len(ingredient_groups) == 1:
        return next(iter(ingredient_groups)), "hoạt chất"
    return "Khác", None


@lru_cache(maxsize=32)
def print_font(size, bold):
    # Liberation Sans has compatible metrics with the Arial print template.
    filename = "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"
    pixels = round(size * 96 / 72)
    for directory in (ROOT, Path(__file__).resolve().parent):
        try:
            return ImageFont.truetype(str(directory / "ADR" / "fonts" / filename), pixels)
        except OSError:
            continue
    return ImageFont.load_default(size=pixels)


@lru_cache(maxsize=4096)
def print_char_width(char, size, bold):
    return print_font(size, bold).getlength(char)


def printed_line_count(cell, width):
    # Excel column widths are based on the width of a digit in the default font.
    max_pixels = max(1, int(width * 7) - 5)
    size = cell.font.sz or 11
    lines = 1
    line_width = 0
    gap = 0
    chars = bold_characters(cell) if cell.value is not None else ()
    for kind, run in groupby(chars, key=lambda pair: (
        "newline" if pair[0] == "\n" else "space" if pair[0].isspace() else "word"
    )):
        widths = [print_char_width(char, size, bold) for char, bold in run]
        if kind == "newline":
            lines += len(widths)
            line_width = gap = 0
        elif kind == "space":
            gap += sum(widths)
        else:
            word_width = sum(widths)
            if line_width and line_width + gap + word_width > max_pixels:
                lines += 1
                line_width = gap = 0
            if word_width <= max_pixels:
                line_width += (gap if line_width else 0) + word_width
            else:
                for char_width in widths:
                    if line_width and line_width + char_width > max_pixels:
                        lines += 1
                        line_width = 0
                    line_width += char_width
            gap = 0
    return lines


def read_report_metadata_from_excel(raw):
    """Read Kho nhan and So PL from cells in the top of Excel Data-Only export."""
    meta = {"khoa": "", "px": ""}
    cells = []
    for row in raw.iloc[:50, :20].itertuples(index=False, name=None):
        for value in row:
            if value is not None and not pd.isna(value):
                cells.append(str(value).strip())
    text = " ".join(cells)
    text = re.sub(r"\s+", " ", text)

    # Labels and values can be in one cell or split into adjacent cells.
    m = re.search(r"Kho\s*nhận\s*:?\s*(.*?)(?=\s+Kho\s*xuất\s*:|\s+Ghi\s*chú\s*:|\s+Số\s*PX\s*:|\s+Số\s*PL\s*:|\s+Số\s*phiếu\s*:|$)", text, re.I)
    if m:
        meta["khoa"] = m.group(1).strip(" :;-")
    # Chi nhan chuoi co chu so (tranh bat nham tieu de "PHIEU XUAT KHO"); uu tien "So PX".
    tok = r"([A-Z0-9./-]*\d[A-Z0-9./-]*)"
    for pat in (r"Số\s*PX\s*:?\s*" + tok, r"Số\s*phiếu\s*xuất(?:\s*kho)?\s*:?\s*" + tok):
        m = re.search(pat, text, re.I)
        if m:
            px_full = re.sub(r"\s+", "", m.group(1)).rstrip(".")
            digits = re.sub(r"\D", "", px_full)
            if digits:
                meta["px"] = digits[-3:].zfill(3)
                meta["px_full"] = px_full
                break

    if IS_TEST:
        # This report labels the receiving ward "Kho Nhập" in its own cell.
        for value in cells:
            match = re.match(r"^Kho\s*(?:nhập|nhận)\s*:\s*(.+)", value, re.I)
            if match:
                meta["khoa"] = re.split(r"\s+Kho\s*xuất\s*:", match.group(1), flags=re.I)[0].strip()
                break

    # So PL co the theo dang cu "So PL: ..." hoac ma khoa nam lien trong chuoi:
    # K17PL2608333 / K47.1PL2605521. Giu ma day du de doi chieu,
    # phan in se rut gon con 3 chu so cuoi o collect("pl_full").
    pl_match = re.search(
        r"Số\s*PL\s*:?\s*([A-Z0-9][A-Z0-9./-]*\d[A-Z0-9./-]*)",
        text, re.I
    )
    if not pl_match:
        pl_match = re.search(
            r"(?<![A-Z0-9])K\s*\d+\s*(?:\.\s*\d+)?\s*PL\s*\d+(?!\d)",
            text, re.I
        )
    if pl_match:
        meta["pl_full"] = re.sub(r"\s+", "", pl_match.group(1) if pl_match.lastindex else pl_match.group(0)).rstrip(".")
    return meta

all_data = []
report_meta = []
input_errors = []
for file_index, path in enumerate(files, 1):
    file_t0 = time.perf_counter()
    profile_event("DANG_DOC_FILE", f"{file_index}/{len(files)} | {path.name}")
    try:
        read_t0 = time.perf_counter()
        raw = pd.read_excel(path, header=None, dtype=object, engine="xlrd" if path.suffix.lower() == ".xls" else "openpyxl")
        profile_event("DOC_XLS_XONG", f"{path.name} | {time.perf_counter()-read_t0:.2f}s | {raw.shape[0]} dong x {raw.shape[1]} cot")
        if raw.empty:
            print(f"Bo qua {path.name}: file rong.")
            input_errors.append(f"{path.name}: file rỗng")
            continue
        header_row = find_header_row(raw)
        split_header = False
        if IS_TEST and header_row is None and raw.shape[1] >= 11:
            # Verified Crystal "Tình hình xuất nội bộ" export: labels span 3 rows.
            for h in range(1, min(len(raw)-1, 60)):
                cells = [norm_header(v) if not pd.isna(v) else "" for v in raw.iloc[h]]
                prev = [norm_header(v) if not pd.isna(v) else "" for v in raw.iloc[h-1]]
                nxt = [norm_header(v) if not pd.isna(v) else "" for v in raw.iloc[h+1]]
                if (cells[0] == "stt" and "ten duoc" in cells[1]
                        and any(v in ("ma duoc", "ma dược") for v in prev)
                        and cells[6] in ("đvt", "dvt")
                        and cells[9] in ("đon gia", "don gia")
                        and cells[10] == "thanh tien" and nxt[8] == "thuc xuat"):
                    header_row = h + 1
                    split_header = True
                    break
        if header_row is None:
            input_errors.append(f"{path.name}: không nhận diện được tiêu đề phiếu")
            print(f"Bo qua {path.name}: khong tu nhan dien duoc dong tieu de. 10 dong dau:")
            print(raw.head(10).fillna("").to_string(index=False, header=False))
            continue

        headers = []
        for x in raw.iloc[header_row].tolist():
            headers.append(str(x).strip() if not pd.isna(x) else "")
        data = raw.iloc[header_row + 1:].copy()
        if split_header:
            headers = ["STT", "Mã", "Tên dược, vật tư, hàm lượng", "Phụ 1", "Phụ 2", "Phụ 3",
                       "ĐVT", "Yêu cầu", "Thực xuất", "Đơn giá", "Thành tiền"] + [f"Phụ {i}" for i in range(11, raw.shape[1])]
        data.columns = headers

        # Normalize likely Crystal field-label variants to the names expected below.
        rename = {}
        for col in data.columns:
            n = norm_header(col)
            if n in ("mã", "ma", "mã thuốc", "ma thuoc", "mã dược", "ma duoc", "code"):
                rename[col] = "Mã"
            elif "tên dược" in n or "ten duoc" in n or "tên thuốc" in n or "ten thuoc" in n:
                rename[col] = "Tên dược, vật tư, hàm lượng"
            elif n in ("đvt", "dvt", "đơn vị tính", "don vi tinh", "đơn vị", "don vi"):
                rename[col] = "ĐVT"
            elif n in ("đơn giá", "don gia", "unit price"):
                rename[col] = "Đơn giá"
            elif n in ("thành tiền", "thanh tien", "amount"):
                rename[col] = "Thành tiền"
            elif n in ("thực xuất", "thuc xuat", "số lượng thực xuất", "so luong thuc xuat"):
                rename[col] = "Thực xuất"
            elif n in ("stt", "số thứ tự", "so thu tu"):
                rename[col] = "STT"
        data = data.rename(columns=rename)

        required = ["Mã", "Tên dược, vật tư, hàm lượng"]
        if any(c not in data.columns for c in required):
            input_errors.append(f"{path.name}: thiếu cột bắt buộc")
            print(f"Bo qua {path.name}: thieu cot bat buoc sau khi nhan dien tieu de.")
            print("Cac cot nhan duoc:", list(data.columns))
            continue

        # Drop blank/non-detail rows. STT is optional in some data-only exports.
        if "STT" in data.columns:
            data = data[pd.to_numeric(data["STT"], errors="coerce").notna()].copy()
        else:
            data = data[data["Mã"].notna()].copy()
        data = data[data["Mã"].astype(str).str.strip().ne("")].copy()
        if data.empty:
            input_errors.append(f"{path.name}: không có dòng chi tiết hợp lệ")
            print(f"Bo qua {path.name}: khong co dong chi tiet.")
            continue

        if IS_TEST:
            if "Thực xuất" not in data.columns:
                raise ValueError(f"{path.name}: thiếu cột Thực xuất (số lượng).")
            quantities = pd.to_numeric(data["Thực xuất"], errors="coerce")
            if quantities.isna().any() or not quantities.map(math.isfinite).all():
                raise ValueError(f"{path.name}: cột Thực xuất có số lượng trống hoặc không hợp lệ.")
            # Both reports use the exact same parser as the normal merge.
            # Multiply the BEFORE quantities by -1; AFTER quantities stay unchanged.
            data["Thực xuất"] = quantities * (-1 if path.stem == "before" else 1)

        # Ensure expected fields exist even if Crystal export omitted one.
        for col in ["ĐVT", "Đơn giá", "Thành tiền", "Thực xuất"]:
            if col not in data.columns:
                data[col] = 0 if col in ("Đơn giá", "Thành tiền", "Thực xuất") else ""
        ingredient_cols = [c for c in data.columns if norm_header(c) in ("hoat chat", "ten hoat chat")]
        data["_ingredients"] = list(data[ingredient_cols].itertuples(index=False, name=None)) if ingredient_cols else [()] * len(data)
        meta = read_report_metadata_from_excel(raw)
        meta["file"] = path.name
        report_meta.append(meta)
        data["Kho nhận"] = meta.get("khoa", "")
        data["Số PX"] = meta.get("px", "")
        data["File nguồn"] = path.name
        all_data.append(data)
        print(f"Da doc {path.name}: {len(data)} dong (tieu de dong {header_row + 1})")
        profile_event("PHAN_TICH_FILE_XONG", f"{path.name} | {len(data)} dong chi tiet | tong {time.perf_counter()-file_t0:.2f}s")
    except Exception as e:
        input_errors.append(f"{path.name}: {e}")
        profile_event("LOI_DOC_FILE", f"{path.name} | {e}")
        print(f"LOI doc {path.name}: {e}")
        if IS_TEST:
            raise

if input_errors:
    raise ValueError("Chưa gộp đủ đầu vào; chưa tạo báo cáo mới. Kiểm tra các file: " + "; ".join(input_errors))
profile_event("KET_THUC_DOC_EXCEL", f"So file hop le={len(all_data)} | Tong dong={sum(len(x) for x in all_data)}")
if IS_TEST and (len(all_data) != 2 or {m["file"] for m in report_meta} != {"before.xls", "after.xls"}):
    raise ValueError("Chưa đọc đủ hai phiếu trước và sau bằng quy trình tổng hợp phiếu lĩnh. Tải hai Excel trung gian để kiểm tra.")
if not all_data:
    raise RuntimeError("Khong tim thay file Excel nao co cau truc phieu xuat hop le.")

# Boi hoan tu truc: gom tat ca phieu, khong tach theo Kho nhan.
reports_by_kho = {"BOI_HOAN_TU_TRUC": all_data}
meta_by_kho = {"BOI_HOAN_TU_TRUC": report_meta}

for khoa_title in ["BOI_HOAN_TU_TRUC"]:
    group_data = reports_by_kho[khoa_title]
    group_meta = meta_by_kho[khoa_title]
    print(f"\n===== DANG TAO FILE CHO KHO NHAN: {khoa_title} =====")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", khoa_title).strip("_") or "CHUA_XAC_DINH"
    output_path = Path(JOB.get("output", ROOT / os.environ.get("GOP_OUT", "Tong_hop_boi_hoan_tu_truc.xlsx")))
    px_numbers = []
    for m in group_meta:
        if m.get("px") and m["px"] not in px_numbers:
            px_numbers.append(m["px"])

    stage_t0 = time.perf_counter()
    merged = pd.concat(group_data, ignore_index=True)
    profile_event("CONCAT_XONG", f"{len(merged)} dong | {time.perf_counter()-stage_t0:.2f}s")
    profile_event("KICH_THUOC_DU_LIEU", f"{len(files)} file Excel | {len(merged)} dong chi tiet")
    merged["Mã"] = merged["Mã"].astype(str).str.strip()
    for col in ["Đơn giá", "Thành tiền"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    template_t0 = time.perf_counter()
    wb = openpyxl.load_workbook(TEMPLATE, rich_text=True)
    if "Sheet2" not in wb.sheetnames or "In" not in wb.sheetnames:
        raise RuntimeError("Mau tong.xlsx phai co sheet Sheet2 va In.")
    profile_event("MO_MAU_XONG", f"{time.perf_counter()-template_t0:.2f}s | {TEMPLATE.name}")
    ws_lookup = wb["Sheet2"]
    lookup = {}
    groups_by_name = defaultdict(set)
    groups_by_ingredient = defaultdict(set)
    for r in range(2, ws_lookup.max_row + 1):
        code = ws_lookup.cell(r, 2).value
        if is_blank(code):
            continue
        name_cell = ws_lookup.cell(r, 3)
        name = name_cell.value
        ingredient = ws_lookup.cell(r, 5).value
        strength_cell = ws_lookup.cell(r, 6)
        strength = strength_cell.value
        group = ws_lookup.cell(r, 15).value
        lookup[str(code).strip()] = {
            "name": name,
            "display_name": catalog_display_name(name_cell, strength_cell) if not is_blank(name) and not IS_TEST else None,
            "unit": ws_lookup.cell(r, 9).value,
            "group": group,
        }
        if not is_blank(group):
            if not is_blank(name):
                for key in drug_name_variants(name, strength):
                    groups_by_name[key].add(str(group).strip())
            if not is_blank(ingredient):
                groups_by_ingredient[drug_key(ingredient)].add(str(group).strip())

    ws_in = wb["In"]
    header_height = ws_in.row_dimensions[1].height
    # Cache mẫu định dạng từ workbook đang mở; không nạp Mau tong.xlsx lần hai.
    group_style_rows = {}
    item_style_row = 3
    style_rows = {}
    for r in range(2, ws_in.max_row + 1):
        group = ws_in.cell(r, 1).value
        code = ws_in.cell(r, 2).value
        if r in (2, 3):
            style_rows[r] = [copy(ws_in.cell(r, c)._style) for c in range(1, 7)]
        if not is_blank(group) and is_blank(code):
            group_style_rows[str(group).strip()] = r
            style_rows[r] = [copy(ws_in.cell(r, c)._style) for c in range(1, 7)]
        elif not is_blank(code):
            item_style_row = r
            style_rows[r] = [copy(ws_in.cell(r, c)._style) for c in range(1, 7)]
            break
    if 2 not in style_rows:
        style_rows[2] = [copy(ws_in.cell(2, c)._style) for c in range(1, 7)]
    if item_style_row not in style_rows:
        style_rows[item_style_row] = [copy(ws_in.cell(item_style_row, c)._style) for c in range(1, 7)]

    # Giữ đúng logic file mẫu đã thống nhất: tổng cột "Đơn giá" nguồn thành "Thực xuất";
    # cột "Thành tiền" nguồn đưa sang cột "Đơn giá" của sheet In.
    group_t0 = time.perf_counter()
    by_code = merged.groupby("Mã", dropna=False, sort=False)
    grouped = by_code.agg(
        qty=("Thực xuất" if IS_TEST else "Đơn giá", "sum"),
        amount=("Đơn giá" if IS_TEST else "Thành tiền", "first" if IS_TEST else "sum"),
        source_name=("Tên dược, vật tư, hàm lượng", "first"),
        source_unit=("ĐVT", "first"),
    ).reset_index()
    profile_event("GROUP_BY_XONG", f"{len(grouped)} ma thuoc | {time.perf_counter()-group_t0:.2f}s")

    new_drugs = {}
    if not IS_TEST:
        unknown = merged.loc[~merged["Mã"].isin(lookup)]
        for unknown_code, rows in unknown.groupby("Mã", sort=False):
            names = rows["Tên dược, vật tư, hàm lượng"].dropna().unique()
            ingredients = [value for values in rows["_ingredients"] for value in values]
            new_drugs[unknown_code] = infer_group(names, ingredients, groups_by_name, groups_by_ingredient)

    show_quantity_parts = re.compile(r"\b(?:drotaverine?|eperisone?|phenytoin)\b", re.IGNORECASE)
    records = []
    for code_value, qty_value, amount_value, source_name, source_unit in grouped.itertuples(index=False, name=None):
        code = str(code_value).strip()
        info = lookup.get(code, {})
        group = info.get("group")
        if code in new_drugs:
            group, matched_by = new_drugs[code]
            if matched_by:
                print(f"Mã mới {code}: phân nhóm {group} theo {matched_by}.")
            else:
                print(f"Mã mới {code}: chưa xác định được nhóm duy nhất, xếp vào Khác.")
        elif is_blank(group):
            group = "Khác"
        group = str(group).strip()
        if info.get("display_name") is not None:
            name = info["display_name"]
        elif is_blank(source_name):
            name = str(info.get("name") or "")
        else:
            name = str(source_name).strip()
            if "(" in name:
                name = name.split("(", 1)[0].strip()
        if not IS_TEST and show_quantity_parts.search(str(name)):
            parts = by_code.get_group(code_value)["Đơn giá"]
            if len(parts) > 1 and all(math.isfinite(value) for value in parts):
                detail = " + ".join(format(value, ".15g").replace(".", ",") for value in parts)
                suffix = f" ({detail})"
                name = name + suffix
        unit = info.get("unit")
        if is_blank(unit):
            unit = source_unit
        records.append({
            "group": group, "code": code, "name": name,
            "qty": float(qty_value or 0), "unit": unit,
            "price": float(amount_value or 0),
        })

    if IS_TEST:
        records = [r for r in records if not math.isclose(r["qty"], 0, abs_tol=1e-9)]

    records.sort(key=lambda x: (str(x["group"]).strip().casefold(), str(x["code"]).strip().casefold()))
    profile_event("TAO_DANH_SACH_MA_XONG", f"{len(records)} ma thuoc")

    # Clear old content but preserve header and worksheet print setup.
    if ws_in.max_row >= 2:
        ws_in.delete_rows(2, ws_in.max_row - 1)

    def apply_style(src_row, dst_row):
        styles = style_rows.get(src_row, style_rows.get(2, []))
        for col, style in enumerate(styles, 1):
            if style is not None:
                ws_in.cell(dst_row, col)._style = copy(style)

    write_t0 = time.perf_counter()
    out_row = 2
    current_group = None
    for rec in records:
        if rec["group"] != current_group:
            current_group = rec["group"]
            apply_style(group_style_rows.get(current_group, 2), out_row)
            ws_in.cell(out_row, 1).value = current_group
            ws_in.cell(out_row, 2).value = None
            ws_in.cell(out_row, 3).value = " "
            for c in range(4, 7):
                ws_in.cell(out_row, c).value = None
            out_row += 1
        apply_style(item_style_row, out_row)
        ws_in.cell(out_row, 1).value = rec["group"]
        ws_in.cell(out_row, 2).value = rec["code"]
        write_drug_name(ws_in.cell(out_row, 3), rec["name"])
        ws_in.cell(out_row, 4).value = rec["qty"]
        ws_in.cell(out_row, 5).value = rec["unit"]
        ws_in.cell(out_row, 6).value = rec["price"]
        out_row += 1
    profile_event("GHI_SHEET_IN_XONG", f"{len(records)} ma thuoc | {time.perf_counter()-write_t0:.2f}s")

    # Refresh the raw-data sheet in the output workbook.
    raw_t0 = time.perf_counter()
    if "Dulieu" in wb.sheetnames:
        ws = wb["Dulieu"]
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)
        cols = list(merged.columns.drop("_ingredients")[:11])
        if IS_TEST and "File nguồn" not in cols:
            cols.append("File nguồn")
        for j, col in enumerate(cols, 1):
            ws.cell(1, j).value = col
        for row in merged[cols].itertuples(index=False, name=None):
            values = []
            for value in row:
                if pd.isna(value):
                    value = None
                elif hasattr(value, "to_pydatetime"):
                    value = value.to_pydatetime()
                values.append(value)
            ws.append(values)
    profile_event("GHI_SHEET_DULIEU_XONG", f"{len(merged)} dong | {time.perf_counter()-raw_t0:.2f}s")

    # Update Pivot data rows; preserve the top 3 rows of the template.
    pivot_t0 = time.perf_counter()
    if "Pivot" in wb.sheetnames:
        ws = wb["Pivot"]
        if ws.max_row > 3:
            ws.delete_rows(4, ws.max_row - 3)
        for i, rec in enumerate(records, 4):
            vals = [rec["code"], rec["name"], rec["unit"], rec["price"], rec["qty"]]
            for j, value in enumerate(vals, 1):
                cell = ws.cell(i, j)
                if j == 2:
                    write_drug_name(cell, value)
                else:
                    cell.value = value
    profile_event("GHI_SHEET_PIVOT_XONG", f"{len(records)} ma thuoc | {time.perf_counter()-pivot_t0:.2f}s")

    # Add report title and PL list above the existing print table.
    ws_in.insert_rows(1, 2)
    ws_in.merge_cells("A1:F1")
    ws_in.merge_cells("A2:F2")
    if MODE == "khoa":
        khos = []
        for m in group_meta:
            k = re.sub(r"^Kho\s+", "", (m.get("khoa") or "").strip(), flags=re.I)
            if k and k.casefold() not in [x.casefold() for x in khos]:
                khos.append(k)
        if len(khos) > 1:
            print("CANH BAO: co nhieu khoa nhan khac nhau: " + ", ".join(khos))
        title_text = "TỔNG HỢP PHIẾU LĨNH KHOA " + (", ".join(khos).upper() if khos else "KHÔNG XÁC ĐỊNH")
    else:
        title_text = "TỔNG HỢP PHIẾU BỒI HOÀN TỦ TRỰC"
    def collect(key):
        # Quy uoc phan in: chi hien 3 chu so cuoi cua moi so phieu.
        # Ma day du van duoc giu trong metadata de nhan dien/doi chieu.
        res = []
        for m in group_meta:
            raw_value = m.get(key) or ""
            digits = re.sub(r"\D", "", raw_value)
            v = digits[-3:].zfill(3) if digits else ""
            if v and v not in res:
                res.append(v)
        return res
    px_list, pl_list = collect("px_full"), collect("pl_full")
    if MODE == "khoa":
        parts = ["Tổng hợp phiếu lĩnh số: " + (", ".join(pl_list) or "KHÔNG ĐỌC ĐƯỢC")]
    else:
        parts = ["Số phiếu xuất kho: " + (", ".join(px_list) or "KHÔNG ĐỌC ĐƯỢC")]
    if IS_TEST:
        ward = str(JOB.get("khoa") or (", ".join(khos) if khos else "")).strip()
        ward = re.sub(r"^(?:Kho\s+)?(?:Trại\s+|Khoa\s+)?", "", ward, flags=re.I).strip()
        title_text = "TỔNG HỢP PHIẾU LĨNH KHOA" + (" " + ward.upper() if ward else "")
        parts = []
    sub_text = "\n".join(parts)
    ws_in["A1"] = title_text
    ws_in["A2"] = sub_text
    from openpyxl.styles import Font, Alignment
    ws_in["A1"].font = Font(name="Times New Roman", size=14, bold=True)
    ws_in["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws_in["A2"].font = Font(name="Times New Roman", size=11, bold=True)
    ws_in["A2"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws_in.row_dimensions[1].height = 24

    if not IS_TEST:
        widths = {col: ws_in.column_dimensions[col].width or 8.43 for col in "ABCDEF"}
        merged_width = sum(widths.values())
        subtitle = ws_in["A2"]
        lines = printed_line_count(subtitle, merged_width)
        ws_in.row_dimensions[2].height = min(409, max(22, lines * subtitle.font.sz * 1.2 + 3))
        ws_in.row_dimensions[3].height = header_height
        # out_row is the next free row before the two title rows were inserted.
        last_print_row = out_row + 1

        ws_in.print_area = f"A1:F{last_print_row}"
        ws_in.row_breaks = RowBreak()
        ws_in.col_breaks = ColBreak()
        ws_in.sheet_properties.pageSetUpPr.fitToPage = True
        ws_in.page_setup.fitToWidth = 1
        ws_in.page_setup.fitToHeight = 0

    if IS_TEST:
        # Remove the old before/after subtitle row entirely.
        ws_in.unmerge_cells("A2:F2")
        ws_in.delete_rows(2)
        ws_in.row_dimensions[2].height = 30
        ws_in.auto_filter.ref = None
        ws_in.print_title_rows = "1:2"
        ws_in.print_area = f"A1:F{ws_in.max_row}"

    save_t0 = time.perf_counter()
    # Generated cells contain data, not formulas; preserve formulas in lookup/template sheets.
    for sheet_name, first_row in [('In',1),('Dulieu',2),('Pivot',4)]:
        if sheet_name in wb.sheetnames:
            for row in wb[sheet_name].iter_rows(min_row=first_row):
                for cell in row:
                    if isinstance(cell.value,str):
                        cell.data_type='s'

    # Publish a complete workbook in one replacement; keep the last good report on failure.
    fd, temporary_output = tempfile.mkstemp(suffix='.xlsx', dir=output_path.parent)
    os.close(fd)
    try:
        wb.save(temporary_output)
        os.replace(temporary_output, output_path)
    finally:
        if os.path.exists(temporary_output):
            os.unlink(temporary_output)
    profile_event("LUU_FILE_KET_QUA_XONG", f"{output_path.name} | {time.perf_counter()-save_t0:.2f}s")
    profile_event("TONG_THOI_GIAN_GOP", f"{time.perf_counter()-_PROFILE_T0:.2f}s")
    print("\\nHOAN TAT")
    print(f"So file Excel da gop: {len(group_data)}")
    print(f"So dong chi tiet sau khi gop: {len(merged)}")
    print(f"So ma thuoc sau khi tong hop: {len(records)}")
    print("Sheet In da sap xep phan nhom A-Z, sau do ma thuoc A-Z.")
    print(f"File ket qua: {output_path}")
