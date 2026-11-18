import time
_T0 = time.perf_counter()
import os, sys, io, re, runpy, contextlib, traceback, subprocess, threading, webbrowser, unicodedata, shutil, json, secrets
from pathlib import Path
from urllib.parse import urlsplit

IS_WIN = os.name == "nt"  # nhanh hơn hàm platform (Python 3.12 trên Windows có thể gọi WMI, chậm)


def _proc_age():
    """Giây kể từ lúc tiến trình được tạo (Windows). Gồm cả bootloader/Python/antivirus, trước khi app.py chạy."""
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        k.GetProcessTimes(k.GetCurrentProcess(), ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
        return time.time() - ((c.dwHighDateTime << 32 | c.dwLowDateTime) / 1e7 - 11644473600)
    except Exception:
        return None


_AGE0 = _proc_age()
from flask import Flask, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from common import atomic_write_json

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
RPT, XLS = ROOT / "RPT", ROOT / "Excel_xuat"
OUTS = {"boi": ROOT / "Tong_hop_boi_hoan_tu_truc.xlsx", "khoa": ROOT / "Tong_hop_phieu_linh_khoa.xlsx"}


def out_of():
    return OUTS["khoa" if request.args.get("mode") == "khoa" else "boi"]
for d in (RPT, XLS):
    d.mkdir(exist_ok=True)

app = Flask(__name__)
# Online deployment is opt-in; the Windows desktop app remains unchanged.
ONLINE_MODE = os.environ.get("PHARMADESK_ONLINE", "0") == "1"
if ONLINE_MODE:
    from werkzeug.middleware.proxy_fix import ProxyFix
    # Render forwards the original public HTTPS scheme behind its reverse proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)  # bớt ghi log từng request
LOCK = threading.Lock()
VERSION = "V3.0"
SESSION_TOKEN = secrets.token_urlsafe(32)
app.config['MAX_CONTENT_LENGTH'] = (20 if ONLINE_MODE else 128) * 1024 * 1024
_STAGING_MUTATIONS = {'/api/reset-session', '/api/clear-rpt', '/api/select-folder',
                      '/api/refresh-folder', '/api/upload', '/api/remove'}


@app.before_request
def online_access_control():
    if not ONLINE_MODE:
        return None
    # Public routes deliberately contain no API, uploads or patient records.
    if request.path in ("/", "/api/health"):
        return None
    blocked = {
        "/api/quit", "/api/open", "/api/clear-rpt",
        "/api/select-folder", "/api/refresh-folder", "/api/ttt/open-kb",
    }
    if request.path in blocked:
        return jsonify(ok=False, msg="Chức năng chỉ hỗ trợ bản cài trên Windows."), 404
    user = os.environ.get("PHARMADESK_USERNAME", "clinical")
    password = os.environ.get("PHARMADESK_PASSWORD", "")
    if len(password) < 16:
        return jsonify(ok=False, msg="Chưa cấu hình mật khẩu mạnh cho khu vực công cụ."), 503
    auth = request.authorization
    if not (auth and auth.type == "basic" and
            secrets.compare_digest(auth.username or "", user) and
            secrets.compare_digest(auth.password or "", password)):
        from flask import Response
        return Response("Authentication required", 401, {
            "WWW-Authenticate": 'Basic realm="PharmaDesk Private Tools", charset="UTF-8"',
            "Cache-Control": "no-store"
        })
    return None


@app.get("/api/health")
def online_health():
    return jsonify(ok=True, service="pharmadesk", online=ONLINE_MODE)


@app.before_request
def validate_request():
    if not ONLINE_MODE and urlsplit('http://' + request.host).hostname not in ('localhost', '127.0.0.1', '::1'):
        return jsonify(ok=False, msg='Máy chủ không hợp lệ.'), 403
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return jsonify(ok=False, msg='Nguồn yêu cầu không hợp lệ.'), 403
        if not secrets.compare_digest(request.headers.get('X-PharmaDesk-Token', ''), SESSION_TOKEN):
            return jsonify(ok=False, msg='Phiên làm việc đã thay đổi. Hãy tải lại trang.'), 403
        if request.is_json and not isinstance(request.get_json(silent=True), dict):
            return jsonify(ok=False, msg='Nội dung yêu cầu phải là một đối tượng JSON.'), 400
        if request.path in _STAGING_MUTATIONS:
            if not LOCK.acquire(blocking=False):
                return jsonify(ok=False, msg='Đang tổng hợp. Vui lòng chờ rồi thử lại.'), 409
            g.staging_locked = True


@app.teardown_request
def release_staging_lock(error=None):
    if getattr(g, 'staging_locked', False):
        g.staging_locked = False
        LOCK.release()


@app.errorhandler(Exception)
def api_error(error):
    if isinstance(error, HTTPException):
        return jsonify(ok=False, msg=error.description), error.code
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return jsonify(ok=False, msg=str(error)), 400
    app.logger.exception('Request failed')
    return jsonify(ok=False, msg='Không xử lý được yêu cầu. Vui lòng xem nhật ký ứng dụng.'), 500


@app.after_request
def no_cache(r):
    r.headers["Cache-Control"] = "no-store"
    if ONLINE_MODE:
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "no-referrer"
        r.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        r.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return r


@app.get("/api/version")
def version():
    return jsonify(v=VERSION)


def listing(folder, exts):
    return [{"name": p.name, "size": p.stat().st_size}
            for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("~$")]


def sh(cmd):
    kw = {}
    if os.name == "nt":  # ẩn cửa sổ console của cscript
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kw = {"startupinfo": si, "creationflags": 0x08000000}
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, stdin=subprocess.DEVNULL,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=600, **kw)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


def _windows_lock_error(path):
    """Return a Windows sharing/access error if an existing workbook is not exclusively writable."""
    if not IS_WIN or not Path(path).exists():
        return None
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p
        ]
        handle = kernel32.CreateFileW(
            str(Path(path)), 0x80000000 | 0x40000000, 0, None, 3, 0x80, None
        )
        if handle == ctypes.c_void_p(-1).value:
            return ctypes.get_last_error()
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    except Exception:
        return None

def merge():
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(str(ROOT / "Gop_va_sort_AZ.py"), run_name="__main__")
        return 0, buf.getvalue()
    except BaseException:
        return 1, buf.getvalue() + traceback.format_exc()


def _isnum(v):
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        float(str(v).strip())
        return True
    except ValueError:
        return False


def meta(path):
    """Read only the report header for preview; stream one column only if row count is absent."""
    is_xls = path.suffix.lower() == ".xls"
    book = sheet = None
    try:
        if is_xls:
            import xlrd
            book = xlrd.open_workbook(str(path), on_demand=True)
            sheet = book.sheet_by_index(0)
            max_rows = sheet.nrows
            sample = [
                [sheet.cell_value(r, c) for c in range(sheet.ncols)]
                for r in range(min(max_rows, 60))
            ]
        else:
            import openpyxl
            book = openpyxl.load_workbook(path, read_only=True, data_only=True)
            sheet = book.worksheets[0]
            max_rows = sheet.max_row or 0
            sample = (
                [
                    list(row)
                    for row in sheet.iter_rows(
                        min_row=1, max_row=min(max_rows, 60), values_only=True
                    )
                ]
                if max_rows else []
            )

        cells = [
            str(v).strip()
            for row in sample[:50]
            for v in row[:20]
            if v is not None
        ]
        text = re.sub(r"\s+", " ", " ".join(cells))

        def g(pattern):
            match = re.search(pattern, text, re.I)
            return match.group(1).strip(" :;-") if match else ""

        px_match = re.search(
            r"(?:Số\s*PX|Số\s*phiếu\s*xuất(?:\s*kho)?)\s*:?\s*([A-Z0-9./-]*\d[A-Z0-9./-]*)",
            text, re.I
        )
        px = re.sub(r"\s+", "", px_match.group(1)).rstrip(".") if px_match else ""
        pl_match = re.search(
            r"Số\s*PL\s*:?\s*([A-Z0-9][A-Z0-9./-]*\d[A-Z0-9./-]*)",
            text, re.I
        )
        if not pl_match:
            pl_match = re.search(
                r"(?<![A-Z0-9])K\s*\d+\s*(?:\.\s*\d+)?\s*PL\s*\d+(?!\d)",
                text, re.I
            )
        pl = (
            re.sub(r"\s+", "", pl_match.group(1) if pl_match.lastindex else pl_match.group(0)).rstrip(".")
            if pl_match else ""
        )
        date_match = re.search(r"Ngày\s*(\d+)\s*Tháng\s*(\d+)\s*Năm\s*(\d+)", text, re.I)
        line_count = g(r"Cộng\s*khoản\s*:?\s*(\d+)")

        if not line_count:
            def norm(value):
                text_value = str(value or "").strip().lower()
                text_value = unicodedata.normalize("NFD", text_value)
                text_value = "".join(
                    ch for ch in text_value if unicodedata.category(ch) != "Mn"
                )
                return re.sub(r"\s+", " ", text_value).strip()

            header_idx = None
            headers = []
            for idx, row in enumerate(sample[:60]):
                values = [norm(v) for v in row]
                code_col = next(
                    (j for j, value in enumerate(values)
                     if value in ("ma", "ma thuoc", "ma duoc", "code")),
                    None
                )
                name_col = next(
                    (j for j, value in enumerate(values)
                     if "ten thuoc" in value or "ten duoc" in value),
                    None
                )
                if code_col is not None and name_col is not None:
                    header_idx, headers = idx, values
                    break

            if header_idx is not None:
                code_col = next(
                    j for j, value in enumerate(headers)
                    if value in ("ma", "ma thuoc", "ma duoc", "code")
                )
                stt_col = next(
                    (j for j, value in enumerate(headers)
                     if value in ("stt", "so thu tu")),
                    None
                )
                count_col = stt_col if stt_col is not None else code_col
                count = 0
                first_data_excel_row = header_idx + 2

                if is_xls:
                    for row_idx in range(first_data_excel_row - 1, max_rows):
                        value = sheet.cell_value(row_idx, count_col)
                        if stt_col is not None:
                            if _isnum(value):
                                count += 1
                        elif value is not None and str(value).strip().lower() not in ("", "nan"):
                            count += 1
                else:
                    for row in sheet.iter_rows(
                        min_row=first_data_excel_row,
                        min_col=count_col + 1,
                        max_col=count_col + 1,
                        values_only=True
                    ):
                        value = row[0] if row else None
                        if stt_col is not None:
                            if _isnum(value):
                                count += 1
                        elif value is not None and str(value).strip().lower() not in ("", "nan"):
                            count += 1
                line_count = str(count)

        return {
            "px": px,
            "px3": re.sub(r"\D", "", px)[-3:].zfill(3) if px else "",
            "pl": pl,
            "kho": g(r"Kho\s*nhận\s*:?\s*(.*?)(?=\s+Kho\s*xuất\s*:|\s+Ghi\s*chú\s*:|\s+Số\s*PX\s*:|\s+Số\s*PL\s*:|$)"),
            "ngay": f"{int(date_match[1]):02d}/{int(date_match[2]):02d}/{date_match[3]}" if date_match else "",
            "lines": line_count,
        }
    finally:
        if book is not None:
            try:
                if is_xls:
                    book.release_resources()
                else:
                    book.close()
            except Exception:
                pass


def _warm():
    """Nạp sẵn pandas (chỉ cần cho bước Gộp) khi app đã mở xong và đang rảnh."""
    try:
        t = time.perf_counter()
        import pandas, openpyxl, xlrd  # noqa: F401
        print(f"Nap san pandas/openpyxl/xlrd: {time.perf_counter() - t:.2f}s")
    except Exception as e:
        print("Bo qua nap san:", e)


_META = {}


def meta_cached(p):
    """Chỉ đọc lại file Excel khi file thay đổi (theo thời gian sửa + dung lượng)."""
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _META:
        if len(_META) > 300:
            _META.clear()
        _META[key] = meta(p)
    return _META[key]


@app.get("/api/preview")
def preview():
    out = []
    for i in listing(XLS, {".xls", ".xlsx"}):
        try:
            m = meta_cached(XLS / i["name"])
        except Exception as e:
            m = {"error": str(e)[:120]}
        out.append({"file": i["name"], **m})
    return jsonify(files=out)


@app.get("/")
def portfolio_home():
    return (ROOT / "portfolio.html").read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/tools")
def index():
    html = (ROOT / 'ui' / 'index.html').read_text(encoding='utf-8')
    return html.replace('__PHARMADESK_TOKEN__', SESSION_TOKEN), 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.get("/api/state")
def state():
    folder = ""
    try:
        if FOLDER_CONFIG.exists():
            folder = json.loads(FOLDER_CONFIG.read_text(encoding="utf-8")).get("folder", "")
    except Exception:
        folder = ""
    return jsonify(rpt=listing(RPT, {".rpt"}), xls=listing(XLS, {".xls", ".xlsx"}),
                   folder=folder, has_result=any(x.exists() for x in OUTS.values()),
                   windows=IS_WIN,
                   template=(ROOT / "Mau tong.xlsx").exists())


# Store user settings in a writable per-user location, not beside the EXE.
# The EXE folder may be read-only (e.g. extracted from a protected ZIP or installed under Program Files).
_USER_DATA = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
CONFIG_DIR = _USER_DATA / "PharmaDesk" / "PhanMemBoiHoan"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
FOLDER_CONFIG = CONFIG_DIR / "SelectedFolder.json"

# Các module báo cáo (ABC/VEN, tương tác thuốc, ADR, TDM): module nào lỗi thì bỏ qua, không ảnh hưởng phần Gộp phiếu.
import importlib
for _name, _sub in (("abcven", "ABCVEN"), ("ttt", "TuongTac"), ("adr", "ADR"), ("tdm", None)):
    try:
        _m = importlib.import_module(_name)
        if _sub:
            _m.init(ROOT, _USER_DATA / "PharmaDesk" / _sub)
        app.register_blueprint(_m.make_blueprint())
    except Exception as _e:
        print(f"Khong nap duoc module {_name}:", _e)


def sync_selected_folder(folder):
    """Đồng bộ tăng dần: chỉ chép file mới/đã đổi, xóa bản chép của file đã biến mất ở nguồn."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        return {"ok": False, "msg": "Thư mục đã chọn không còn tồn tại."}
    app_root = ROOT.resolve()
    internal_dirs = {(ROOT / "RPT").resolve(), (ROOT / "Excel_xuat").resolve()}
    if folder == app_root or folder in internal_dirs or app_root in folder.parents:
        return {"ok": False, "msg": "Không chọn thư mục nội bộ RPT/Excel_xuat của Pharma Desk. Hãy chọn thư mục chứa phiếu gốc bên ngoài thư mục phần mềm."}
    previous = {"rpt": [], "xls": []}
    try:
        if FOLDER_CONFIG.exists():
            previous = json.loads(FOLDER_CONFIG.read_text(encoding="utf-8")).get("managed", previous)
    except Exception:
        pass
    prev = {k: set(previous.get(k, [])) for k in ("rpt", "xls")}
    managed = {"rpt": [], "xls": []}
    saved = {"rpt": 0, "xls": 0}
    skipped, changed = 0, False
    for src in sorted(folder.rglob("*")):
        try:
            resolved_src = src.resolve()
            if resolved_src == app_root or app_root in resolved_src.parents:
                continue
        except OSError:
            continue
        if not src.is_file() or src.name.startswith("~$"):
            continue
        ext = src.suffix.lower()
        kind = "rpt" if ext == ".rpt" else "xls" if ext in (".xls", ".xlsx") else None
        if not kind:
            continue
        target = RPT if kind == "rpt" else XLS
        dest = target / src.name
        stem, suffix, n = src.stem, src.suffix, 2
        while (dest.exists() and dest.name not in prev[kind]) or dest.name in managed[kind]:
            dest = target / f"{stem}_{n}{suffix}"
            n += 1
        try:
            same = False
            if dest.exists():
                a, b = src.stat(), dest.stat()
                same = a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns
            if not same:
                shutil.copy2(src, dest)
                changed = True
            managed[kind].append(dest.name)
            saved[kind] += 1
        except OSError:
            skipped += 1
    for kind, target in (("rpt", RPT), ("xls", XLS)):
        for name in prev[kind] - set(managed[kind]):
            try:
                (target / Path(name).name).unlink(missing_ok=True)
                changed = True
            except OSError:
                pass
    atomic_write_json(FOLDER_CONFIG, {"folder": str(folder), "managed": managed})
    return {"ok": True, "saved": sum(saved.values()), "rpt": saved["rpt"], "xls": saved["xls"],
            "skipped": skipped, "folder": str(folder), "changed": changed}


def clean_staging():
    """Xóa file nhập tạm trong RPT/Excel_xuat; không đụng dữ liệu thư mục nguồn."""
    removed = {"rpt": 0, "xls": 0}
    errors = []
    for folder, kind, exts in ((RPT, "rpt", {".rpt"}),
                               (XLS, "xls", {".xls", ".xlsx"})):
        folder.mkdir(exist_ok=True)
        for item in folder.iterdir():
            if item.is_file() and item.suffix.lower() in exts and not item.name.startswith("~$"):
                try:
                    item.unlink()
                    removed[kind] += 1
                except OSError as exc:
                    errors.append(f"{item.name}: {exc}")
    # Keep the last chosen folder, but do not treat its old copies as currently loaded.
    cfg = {}
    try:
        if FOLDER_CONFIG.exists():
            cfg = json.loads(FOLDER_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    if cfg.get("folder"):
        cfg["managed"] = {"rpt": [], "xls": []}
        atomic_write_json(FOLDER_CONFIG, cfg)
    return {"ok": not errors, "removed": removed, "errors": errors}


@app.post("/api/reset-session")
def reset_session():
    return jsonify(clean_staging())


# Keep staged inputs across restarts and when opening a second application window.


@app.post("/api/select-folder")
def select_folder():
    """Open the native Windows folder picker, then synchronize selected folder."""
    if not IS_WIN:
        return jsonify(ok=False, msg="Chức năng chọn thư mục trực tiếp chỉ hỗ trợ Windows.")
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        folder = filedialog.askdirectory(
            parent=root, title="Chọn thư mục chứa phiếu RPT / Excel", mustexist=True
        )
        root.destroy()
        if not folder:
            return jsonify(ok=True, cancelled=True, saved=0, rpt=0, xls=0)
        return jsonify(sync_selected_folder(folder))
    except Exception as e:
        return jsonify(ok=False, msg=f"Không thể chọn hoặc lưu thông tin thư mục: {e}")


@app.post("/api/refresh-folder")
def refresh_folder():
    """Re-scan the last selected folder and update imported files."""
    try:
        if not FOLDER_CONFIG.exists():
            return jsonify(ok=False, msg="Bạn chưa chọn thư mục nguồn. Hãy bấm Chọn thư mục trước.")
        cfg = json.loads(FOLDER_CONFIG.read_text(encoding="utf-8"))
        folder = cfg.get("folder", "")
        if not folder:
            return jsonify(ok=False, msg="Chưa lưu thư mục nguồn. Hãy chọn lại thư mục.")
        return jsonify(sync_selected_folder(folder))
    except Exception as e:
        return jsonify(ok=False, msg=f"Không làm mới được thư mục: {e}")


@app.post("/api/upload")
def upload():
    n = 0
    for f in request.files.getlist("files"):
        name = Path(f.filename).name
        ext = Path(name).suffix.lower()
        dest = RPT if ext == ".rpt" else XLS if ext in (".xls", ".xlsx") else None
        if dest:
            f.save(dest / name)
            n += 1
    return jsonify(saved=n)


@app.post("/api/clear-rpt")
def clear_rpt():
    """Delete originals in the confirmed source folder, then clear staged copies."""
    confirmed = (request.get_json(silent=True) or {}).get("folder")
    try:
        cfg = json.loads(FOLDER_CONFIG.read_text(encoding="utf-8")) if FOLDER_CONFIG.exists() else {}
        selected = cfg.get("folder")
        if not selected or confirmed != selected:
            return jsonify(ok=False, msg="Thư mục nguồn chưa được chọn hoặc đã thay đổi. Hãy kiểm tra và xác nhận lại."), 409

        folder = Path(selected)
        resolved = folder.resolve(strict=True)
        app_root = ROOT.resolve()
        if (not resolved.is_dir() or resolved != folder or resolved == resolved.parent
                or resolved == app_root or app_root in resolved.parents
                or resolved in (RPT.resolve(), XLS.resolve())):
            return jsonify(ok=False, msg="Thư mục nguồn không hợp lệ. Hãy chọn lại thư mục chứa phiếu gốc."), 400

        def fail_scan(exc):
            raise exc

        originals = []
        for directory, subfolders, filenames in os.walk(resolved, onerror=fail_scan):
            parent = Path(directory)
            for name in subfolders[:]:
                child = parent / name
                # Exclude symlinks and Windows junctions, and skip app files.
                if child == app_root or child.is_symlink() or child.resolve() != child:
                    subfolders.remove(name)
            for name in filenames:
                item = parent / name
                if (item.suffix.lower() == ".rpt" and not name.startswith("~$")
                        and not item.is_symlink() and item.is_file()):
                    originals.append(item)
    except (OSError, ValueError) as exc:
        return jsonify(ok=False, msg=f"Không đọc được thư mục nguồn: {exc}"), 400

    removed_source = 0
    errors = []
    for item in originals:
        try:
            if item.is_symlink() or item.resolve() != item:
                raise OSError("Đường dẫn đã thay đổi trong lúc làm sạch.")
            item.unlink()
            removed_source += 1
        except OSError as exc:
            errors.append(f"{item.relative_to(resolved)}: {exc}")

    if errors:
        return jsonify(ok=False, removed_source=removed_source, errors=errors,
                       msg="Có file RPT gốc chưa xóa được. Hãy đóng file đang mở rồi thử lại.")

    result = clean_staging()
    return jsonify(ok=result["ok"], removed_source=removed_source,
                   removed_staging=result["removed"]["rpt"], removed_xls=result["removed"]["xls"],
                   errors=result["errors"], msg=f"Đã xóa {removed_source} file RPT gốc trong {folder}.")


@app.post("/api/remove")
def remove():
    d = request.get_json()
    folder, exts = (RPT, {".rpt"}) if d.get("kind") == "rpt" else (XLS, {".xls", ".xlsx"})
    names = [Path(d["name"]).name] if d.get("name") else [i["name"] for i in listing(folder, exts)]
    for n in names:
        (folder / n).unlink(missing_ok=True)
    return jsonify(ok=True)


@app.post("/api/run")
def run():
    if not LOCK.acquire(blocking=False):
        return jsonify(ok=False, log="Đang xử lý, vui lòng chờ...")
    try:
        d = request.get_json()
        mode = "khoa" if d.get("mode") == "khoa" else "boi"
        os.environ["GOP_MODE"] = mode
        os.environ["GOP_OUT"] = OUTS[mode].name
        log = ""
        lock_error = _windows_lock_error(OUTS[mode])
        if lock_error in (32, 33):
            return jsonify(ok=False, log=(
                "RESULT_FILE_OPEN|" + str(OUTS[mode]) +
                "\\nFile Excel kết quả đang được mở hoặc bị chương trình khác khóa."
            ))
        if lock_error == 5:
            return jsonify(ok=False, log=(
                "RESULT_FILE_ACCESS_DENIED|" + str(OUTS[mode]) +
                "\\nWindows từ chối quyền ghi file kết quả."
            ))
        if d.get("export", True):
            export_t0 = time.perf_counter()
            if not IS_WIN:
                return jsonify(ok=False, log="Bước xuất RPT chỉ chạy trên Windows có Crystal Reports. "
                                             "Hãy bật 'Chỉ gộp' và dùng file .xls đã xuất.")
            cs = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "SysWOW64" / "cscript.exe"
            code, out = sh([str(cs) if cs.exists() else "cscript", "//nologo", "Xuat_RPT_sang_XLS.vbs"])
            log += "== BƯỚC 1: XUẤT RPT -> XLS ==\n" + out + "\n"
            log += f"\n[TIME] Thoi gian xuat RPT: {time.perf_counter()-export_t0:.2f}s\n"
            if code:
                return jsonify(ok=False, log=log)
        merge_t0 = time.perf_counter()
        code, out = merge()
        log += "== BƯỚC 2: GỘP & SẮP XẾP A-Z ==\n" + out
        log += f"\n[TIME] Thoi gian gop Excel: {time.perf_counter()-merge_t0:.2f}s\n"
        return jsonify(ok=code == 0, log=log)
    finally:
        LOCK.release()


_RES = {}


@app.get("/api/result")
def result():
    fp = out_of()
    if not fp.exists():
        return jsonify(items=[])
    st = fp.stat()
    key = (str(fp), st.st_mtime_ns, st.st_size)
    if key not in _RES:
        import openpyxl
        wb = openpyxl.load_workbook(fp, data_only=True, read_only=True)
        rows = [(list(r) + [None] * 6)[:6] for r in wb["In"].iter_rows(max_col=6, values_only=True)]
        wb.close()
        items = [{"group": r[0], "code": r[1], "name": (r[2] or "").strip(),
                  "qty": r[3], "unit": r[4], "amount": r[5]} for r in rows[3:] if r[1]]
        _RES.clear()
        _RES[key] = {"title": rows[0][0], "sub": rows[1][0], "items": items, "mtime": st.st_mtime}
    return jsonify(_RES[key])


@app.get("/api/download")
def download():
    return send_file(out_of(), as_attachment=True)


@app.post("/api/quit")
def quit_app():
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify(ok=True)


@app.post("/api/open")
def open_excel():
    fp = out_of()
    if not fp.exists():
        return jsonify(ok=False, msg="Chưa có file kết quả. Hãy bấm Bắt đầu tổng hợp trước.")
    if not IS_WIN:
        return jsonify(ok=False, msg="Chỉ mở được bằng Excel trên Windows. Hãy dùng nút Tải Excel.")
    os.startfile(str(fp))
    return jsonify(ok=True)


if __name__ == "__main__":
    import socket, json

    # Khi đóng gói --noconsole, lưu nhật ký vào Logs thay vì hiện cửa sổ đen.
    LOG_DIR = ROOT / "Logs"
    LOG_DIR.mkdir(exist_ok=True)
    LOG_FILE = LOG_DIR / "PhanMemBoiHoan.log"
    _log_stream = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_stream
    sys.stderr = _log_stream

    print()
    print("=" * 60)
    print(f"Khoi dong Phan mem Boi hoan {VERSION}")

    def free(pt):
        s = socket.socket()
        ok = s.connect_ex(("127.0.0.1", pt)) != 0
        s.close()
        return ok

    port = 5173
    if not free(port):
        base = f"http://127.0.0.1:{port}"
        import urllib.request
        try:
            with urllib.request.urlopen(base + "/api/version", timeout=1.5) as r:
                same = json.load(r).get("v") == VERSION
        except Exception:
            same = False
        if same:  # đã chạy đúng bản này: chỉ mở lại trang
            webbrowser.open(base)
            sys.exit()
        try:  # bản cũ đang chạy: yêu cầu nó thoát để thay bằng bản mới
            urllib.request.urlopen(urllib.request.Request(base + "/api/quit", method="POST"), timeout=2)
        except Exception:
            pass
        for _ in range(30):
            if free(port):
                break
            time.sleep(0.1)
        while not free(port) and port < 5183:  # bản quá cũ không tự thoát được: dùng cổng khác
            port += 1
    url = f"http://127.0.0.1:{port}"
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", port, app, threaded=True)  # đã lắng nghe: trình duyệt mở được ngay
    # Nạp thư viện nặng khi phần mềm đang rảnh, không tranh tài nguyên với Crystal Reports ở bước 3.
    threading.Timer(1.5, lambda: threading.Thread(target=_warm, daemon=True).start()).start()
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    age = _proc_age()
    extra = (f" | TU LUC MO EXE: {age:.2f}s (Python/exe khoi dong truoc app.py: {_AGE0:.2f}s)"
             if age is not None and _AGE0 is not None else "")
    print(f"Phan mem {VERSION} san sang sau {time.perf_counter() - _T0:.2f}s{extra} tai {url}")
    srv.serve_forever()
