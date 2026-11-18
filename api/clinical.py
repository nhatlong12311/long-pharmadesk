"""Request-scoped Flask API for the four Vercel tools."""

import base64
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import abcven
import adr
import tdm
import ttt
from common import atomic_write_json, request_data

MAX_BYTES = 4_400_000
PERIOD = re.compile(r"ABCVEN/Lich_su/(1999|20\d\d|2100)-(0[1-9]|1[0-2])\.json")
WATCH = "ABCVEN/hoat_chat_theo_doi.json"
RULES = "TuongTac/Quy_tac_tuong_tac.json"
ABC_GENERATE = {"/api/abc/generate", "/api/abc/generate-four"}
REPORTS = ABC_GENERATE | {"/api/abc/export-month", "/api/abc/compare-month", "/api/ttt/generate"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES

for module, directory in ((abcven, "ABCVEN"), (adr, "ADR"), (ttt, "TuongTac")):
    # Only the immutable template location and a directory name are global.
    module.CFG.update(root=ROOT, data=Path(directory))
app.register_blueprint(abcven.make_blueprint())
app.register_blueprint(adr.make_blueprint(inline_reports=True))
app.register_blueprint(ttt.make_blueprint(state_post=True))
app.register_blueprint(tdm.make_blueprint())


@app.get("/api/version")
def version():
    return jsonify(v="V3.0", processing="server")


def state_input():
    if request.is_json:
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError("Nội dung yêu cầu phải là một đối tượng JSON.")
        return value.get("_state", {})
    if request.mimetype == "multipart/form-data":
        attachment = request.files.get("_state")
        if attachment:
            return json.load(attachment.stream)
    return {}


@app.before_request
def prepare_request():
    path = request.path
    if re.fullmatch(r"/api/(abc|ttt|adr)/(download|view|open|open-kb|draft|drafts|draft/delete)", path):
        return jsonify(ok=False, msg="Dữ liệu này được lưu trong trình duyệt."), 404
    if request.method == "POST" and request.content_length and request.content_length > MAX_BYTES:
        return jsonify(ok=False, msg="Tổng dung lượng mỗi lượt gửi lên Vercel tối đa 4,4 MB."), 413
    browser_state = state_input() if request.method == "POST" else {}
    if not isinstance(browser_state, dict):
        raise ValueError("Dữ liệu lịch sử không hợp lệ.")

    # TDM does not use the filesystem.
    if not path.startswith(("/api/abc/", "/api/ttt/", "/api/adr/")):
        return
    g.scratch = tempfile.TemporaryDirectory(prefix="pharmadesk-vercel-")
    root = Path(g.scratch.name)
    g.scope = request_data.set(root)
    folder = {"abc": "ABCVEN", "adr": "ADR", "ttt": "TuongTac"}[path.split("/")[2]]
    (root / folder / "Bao_cao").mkdir(parents=True)
    g.input_mtime = {}
    for key, value in browser_state.items():
        allowed_abc = path in ABC_GENERATE | {"/api/abc/watch"} and (
            key == WATCH and isinstance(value, list)
            or path in ABC_GENERATE and PERIOD.fullmatch(key) and isinstance(value, dict)
        )
        allowed_ttt = folder == "TuongTac" and key == RULES and isinstance(value, dict)
        if allowed_abc or allowed_ttt:
            file = root / key
            atomic_write_json(file, value)
            g.input_mtime[key] = file.stat().st_mtime_ns


@app.after_request
def finalize_request(response):
    path = request.path
    root = request_data.get()
    if root and response.is_json and response.status_code == 200:
        output = response.get_json()
        if output.get("ok"):
            if path in REPORTS:
                directory = "ABCVEN" if path.startswith("/api/abc/") else "TuongTac"
                name = output["name"]
                report_path = root / directory / "Bao_cao" / name
                if report_path.stat().st_size > MAX_BYTES * 3 // 4:
                    return too_large()
                output["inline_file"] = base64.b64encode(report_path.read_bytes()).decode("ascii")
            updates = {}
            if path in ABC_GENERATE:
                for file in (root / "ABCVEN" / "Lich_su").glob("*.json"):
                    key = file.relative_to(root).as_posix()
                    # Include updated periods, including an uploaded previous period.
                    if file.stat().st_mtime_ns != g.input_mtime.get(key):
                        updates[key] = json.loads(file.read_bytes())
            if path in ABC_GENERATE | {"/api/abc/watch"} and (root / WATCH).exists():
                updates[WATCH] = json.loads((root / WATCH).read_bytes())
            if path == "/api/abc/watch" and not (root / WATCH).exists():
                updates[WATCH] = None
            if path == "/api/ttt/rules":
                updates[RULES] = json.loads((root / RULES).read_bytes())
            if updates:
                output["_state"] = updates
            response.set_data(app.json.dumps(output))
    if response.calculate_content_length() and response.calculate_content_length() > MAX_BYTES:
        response = too_large()
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def too_large():
    response = jsonify(ok=False, msg="Kết quả quá lớn cho một lượt trả về của Vercel. Hãy chia nhỏ dữ liệu đầu vào.")
    response.status_code = 413
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.teardown_request
def discard_request(_error):
    if "scratch" in g:
        request_data.reset(g.scope)
        g.scratch.cleanup()


@app.errorhandler(Exception)
def handle_error(error):
    if isinstance(error, HTTPException):
        if error.code == 413:
            return jsonify(ok=False, msg="Tổng dung lượng mỗi lượt gửi lên Vercel tối đa 4,4 MB."), 413
        return jsonify(ok=False, msg=error.description), error.code
    if isinstance(error, (TypeError, ValueError, KeyError)):
        return jsonify(ok=False, msg=str(error)), 400
    return jsonify(ok=False, msg="Máy chủ chưa xử lý được yêu cầu. Vui lòng thử lại."), 500


flask_wsgi = app.wsgi_app


def routed_wsgi(environ, start_response):
    route = parse_qs(environ.get("QUERY_STRING", "")).get("_clinical_path", [])
    if route and not environ.get("PATH_INFO", "").startswith(("/api/abc/", "/api/ttt/", "/api/adr/", "/api/tdm/")):
        environ["PATH_INFO"] = "/api/" + route[-1].lstrip("/")
    return flask_wsgi(environ, start_response)


app.wsgi_app = routed_wsgi
