"""Run the original clinical routes in the browser's Python worker."""

import io
import os
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

import abcven
import adr
import tdm
import ttt

ROOT = Path(__file__).parent
DATA = Path("/pharmadesk-data")
MAX_UPLOAD = 20 * 1024 * 1024
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

for module, directory in ((abcven, "ABCVEN"), (ttt, "TuongTac"), (adr, "ADR")):
    module.init(ROOT, DATA / directory)
    app.register_blueprint(module.make_blueprint())
app.register_blueprint(tdm.make_blueprint())

# The original inline PDF preview is used so generated reports travel back to
# the page in the same response. There is no file server in the browser.
os.environ["PHARMADESK_ONLINE"] = "1"


@app.get("/api/version")
def version():
    return jsonify(v="V3.0")


@app.before_request
def check_json():
    if request.is_json and not isinstance(request.get_json(silent=True), dict):
        return jsonify(ok=False, msg="Nội dung yêu cầu phải là một đối tượng JSON."), 400


@app.errorhandler(Exception)
def request_error(error):
    if isinstance(error, HTTPException):
        return jsonify(ok=False, msg=error.description), error.code
    if isinstance(error, (TypeError, ValueError, KeyError)):
        return jsonify(ok=False, msg=str(error)), 400
    app.logger.exception("Browser request failed")
    return jsonify(ok=False, msg="Không xử lý được yêu cầu trên thiết bị."), 500


def handle_request(method, path, mime_type, body):
    with app.test_client().open(
        path, method=method, input_stream=io.BytesIO(bytes(body)), content_type=mime_type
    ) as response:
        return response.status_code, list(response.headers.items()), response.get_data()
