"""Build PharmaDesk for GitHub Pages or for the Vercel server API."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PYODIDE_VERSION = "0.29.3"
PYODIDE = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
SHEETJS = "https://cdn.sheetjs.com/xlsx-0.20.3/package/"
CORE = {
    "pyodide.mjs": "23213d27e9dacbda6f25f955fb38dabfc40ada082c04ee253047ea5dddcaa3b5",
    "pyodide.asm.js": "1263f02b5b26099b96112378156f242dd98b39a8201ba7765e5fe3d455c5ce91",
    "pyodide.asm.wasm": "e2f4ee75b325e35eb31bfb8c613d4dd5098f5502c156a97847686875b5025480",
    "pyodide-lock.json": "3256ffc76388de0e37f4b34d42ab484268d1afc675179ff97b2a5bb14f84ccac",
    "python_stdlib.zip": "4298b6ee445cb724c3973437da47789752b9e6ff4e26619026b283ec801fc46b",
}
WASM_PACKAGES = ["lxml", "markupsafe", "pillow", "typing-extensions", "xlrd"]
MODULES = ["abcven.py", "adr.py", "common.py", "tdm.py", "ttt.py"]
TEMPLATES = [
    "ABC_VEN/Mau_bao_cao_ABC_VEN.docx",
    "ADR/Mau_bao_cao_ADR.pdf",
    "ADR/fonts/LiberationSans-Regular.ttf",
    "ADR/fonts/LiberationSans-Bold.ttf",
    "TUONG_TAC/Mau_tuong_tac_thuoc.docx",
    "TUONG_TAC/Quy_tac_tuong_tac.json",
    "TUONG_TAC/mahoatchat.xlsx",
]


def fetch(url, path, digest=None):
    if digest and path.is_file() and sha256(path.read_bytes()).hexdigest() == digest:
        return
    content = subprocess.check_output(["curl", "--fail", "--silent", "--show-error", "--location",
                                      "--retry", "2", "--max-time", "40", url])
    if digest and sha256(content).hexdigest() != digest:
        raise ValueError(f"Checksum mismatch for {path.name}")
    path.write_bytes(content)


def replacements(html, edits):
    for before, after in edits:
        if html.count(before) != 1:
            raise ValueError(f"Could not find the UI element to replace: {before}")
        html = html.replace(before, after)
    return html


def prepare_browser_data(pure):
    # Reuse the locked pure-Python wheels already downloaded for the browser.
    paths = [str(ROOT)]
    for package in ("openpyxl", "et_xmlfile"):
        (wheel,) = pure.glob(package + "-*.whl")
        paths.append(str(wheel))
    sys.path[:0] = paths
    try:
        from abcven import STAT_FIELDS
        from ttt import read_kb_workbook

        fields = [{"key": key, "label": label} for key, label in STAT_FIELDS]
        kb = read_kb_workbook(ROOT / "TUONG_TAC" / "Co_che_tuong_tac.xlsx")
        return fields, kb
    finally:
        del sys.path[:len(paths)]


def copy_pharmacount(output):
    """Publish only the two browser assets, never private test/SQL/doc files."""
    source = ROOT / "pharmacount"
    if not (source / "index.html").is_file():
        return
    target = output / "pharmacount"
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "pack-worker.js"):
        shutil.copyfile(source / filename, target / filename)


def build(output):
    requirements = WEB / "requirements.txt"
    runtime_version = sha256(
        json.dumps([CORE, WASM_PACKAGES], sort_keys=True).encode() + requirements.read_bytes()
    ).hexdigest()[:16]
    runtime = output / "runtime" / runtime_version
    pure = runtime / "wheels"
    pure.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda pair: fetch(PYODIDE + pair[0], runtime / pair[0], pair[1]), CORE.items()))
        lock = json.loads((runtime / "pyodide-lock.json").read_text(encoding="utf-8"))
        for key in WASM_PACKAGES:
            entry = lock["packages"][key]
            name = entry["file_name"]
            fetch(PYODIDE + name, runtime / name, entry["sha256"])

    subprocess.run([
        sys.executable, "-m", "pip", "download", "-r", str(requirements),
        "--require-hashes", "--no-deps", "--only-binary=:all:", "--platform", "any", "-d", str(pure),
    ], check=True)
    (runtime / "wheels.json").write_text(
        json.dumps({"wasm": WASM_PACKAGES, "pure": sorted(path.name for path in pure.glob("*.whl"))}),
        encoding="utf-8",
    )

    fields, kb = prepare_browser_data(pure)
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        files = [(WEB / "browser_backend.py", "browser_backend.py")]
        files.extend((ROOT / name, name) for name in MODULES + TEMPLATES)
        for path, name in files:
            archive.writestr(ZipInfo(name), path.read_bytes(), compress_type=ZIP_DEFLATED)
        archive.writestr(ZipInfo("TUONG_TAC/Co_che_tuong_tac.json"),
                         json.dumps(kb, ensure_ascii=False).encode("utf-8"), compress_type=ZIP_DEFLATED)
    data = source.getvalue()
    source_name = f"python-{sha256(data).hexdigest()[:16]}.zip"
    (output / source_name).write_bytes(data)

    worker = replacements((WEB / "worker.mjs").read_text(encoding="utf-8"), [
        ("__RUNTIME_VERSION__", runtime_version), ("__PYTHON_SOURCE__", source_name),
    ])
    (output / "worker.mjs").write_text(worker, encoding="utf-8")
    worker_version = sha256(worker.encode()).hexdigest()[:16]
    local = replacements((WEB / "local.js").read_text(encoding="utf-8"), [
        ("__WORKER_VERSION__", worker_version),
        ("__ABC_FIELDS__", json.dumps(fields, ensure_ascii=False)),
    ])
    local_version = sha256(local.encode()).hexdigest()[:16]
    (output / "local.js").write_text(local, encoding="utf-8")
    build_ui(output, f"local.js?v={local_version}")

    for name in ("local.css", "runtime-cache.js"):
        shutil.copyfile(WEB / name, output / name)
    shutil.copyfile(ROOT / "docs" / "rules.json", output / "rules.json")
    fetch(SHEETJS + "dist/xlsx.full.min.js", output / "xlsx.full.min.js",
          "cc015130aa8521e7f088f88898eba949ccdcbfb38df0bd129b44b7273c3a6f41")
    fetch(SHEETJS + "LICENSE", output / "LICENSE-SheetJS.txt")
    fetch(f"https://raw.githubusercontent.com/pyodide/pyodide/{PYODIDE_VERSION}/LICENSE", runtime / "LICENSE.txt")
    beta = (ROOT / "docs" / "browser.html").read_text(encoding="utf-8")
    (output / "browser.html").write_text(beta.replace(SHEETJS + "dist/xlsx.full.min.js", "./xlsx.full.min.js"), encoding="utf-8")
    (output / ".nojekyll").touch()
    copy_pharmacount(output)
    quiz = ROOT / 'pharmaquiz'
    if (quiz / 'index.html').is_file() and (quiz / 'questions.json').is_file():
        target = output / 'pharmaquiz'
        target.mkdir(parents=True, exist_ok=True)
        for filename in ('index.html', 'questions.json'):
            shutil.copyfile(quiz / filename, target / filename)


def build_ui(output, script, *, server=False):
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    banner = ("" if server else
              '<div class="portfolio-back"><span>PHARMADESK 3.0 · XỬ LÝ TRÊN THIẾT BỊ</span><a href="./browser.html">Bản web nhẹ</a></div>')
    edits = [
        ('</head>', '<link rel="stylesheet" href="./local.css">\n</head>'),
        ('<div class="portfolio-back"><a href="/">← LONG / Personal Portfolio</a><span class="tag">PHARMADESK 3.0 · LOCAL CLINICAL WORKSPACE</span></div>', banner),
        ('<script>\n// Attach the per-process token', f'<script src="./{script}"></script>\n<script>\n// Attach the per-process token'),
        ("const module=new URLSearchParams(location.search).get('module');",
         "const requested=new URLSearchParams(location.search).get('module')||location.hash.slice(1);\n const module=['abc','ttt','tdm','adr'].includes(requested)?requested:'abc';"),
        ("refresh();load();guideRender();", ""),
        ("__PHARMADESK_TOKEN__", ""),
    ]
    if not server:
        edits.append(('    </div>\n</div>\n\n<main id="truMain"',
                      '    </div>\n  <div id="localStatus" hidden><span id="localStatusMessage" role="status"></span><button type="button" id="localRetry" class="ghost" hidden>Thử lại</button></div>\n</div>\n\n<main id="truMain"'))
    (output / "index.html").write_text(replacements(html, edits), encoding="utf-8")


def build_server(output):
    sys.path.insert(0, str(ROOT))
    from abcven import STAT_FIELDS

    output.mkdir(parents=True, exist_ok=True)
    for name in ("local.css", "adr-storage.mjs"):
        shutil.copyfile(WEB / name, output / name)
    storage_version = sha256((output / "adr-storage.mjs").read_bytes()).hexdigest()[:16]
    fields = [{"key": key, "label": label} for key, label in STAT_FIELDS]
    script = replacements((WEB / "server.js").read_text(encoding="utf-8"), [
        ("__ABC_FIELDS__", json.dumps(fields, ensure_ascii=False)),
        ("__STORAGE_VERSION__", storage_version),
    ])
    (output / "server.js").write_text(script, encoding="utf-8")
    build_ui(output, "server.js?v=" + sha256(script.encode()).hexdigest()[:16], server=True)
    portfolio = (ROOT / "portfolio.html").read_text(encoding="utf-8")
    portfolio = portfolio.replace('href="/tools?view=clinical&amp;module=', 'href="/?module=')
    (output / "portfolio.html").write_text(portfolio, encoding="utf-8")
    copy_pharmacount(output)


if __name__ == "__main__":
    output = Path(sys.argv[1]).resolve()
    if "--server" in sys.argv[2:]:
        build_server(output)
    else:
        build(output)
