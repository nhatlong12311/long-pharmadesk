"""Build the GitHub Pages site with all Python dependencies served locally."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

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
    "TUONG_TAC/Co_che_tuong_tac.xlsx",
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


def build(output):
    runtime = output / "runtime"
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
        sys.executable, "-m", "pip", "download", "-r", str(WEB / "requirements.txt"),
        "--require-hashes", "--no-deps", "--only-binary=:all:", "--platform", "any", "-d", str(pure),
    ], check=True)
    (runtime / "wheels.json").write_text(
        json.dumps({"wasm": WASM_PACKAGES, "pure": sorted(path.name for path in pure.glob("*.whl"))}),
        encoding="utf-8",
    )

    with ZipFile(output / "python.zip", "w", ZIP_DEFLATED) as archive:
        archive.write(WEB / "browser_backend.py", "browser_backend.py")
        for name in MODULES + TEMPLATES:
            archive.write(ROOT / name, name)

    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    html = replacements(html, [
        ('</head>', '<link rel="stylesheet" href="./local.css">\n</head>'),
        ('<div class="portfolio-back"><a href="/">← LONG / Personal Portfolio</a><span class="tag">PHARMADESK 3.0 · LOCAL CLINICAL WORKSPACE</span></div>',
         '<div class="portfolio-back"><span>PHARMADESK 3.0 · XỬ LÝ TRÊN THIẾT BỊ</span><a href="./browser.html">Bản web nhẹ</a></div>'),
        ('    </div>\n</div>\n\n<main id="truMain"', '    </div>\n  <div id="localStatus"><span id="localStatusMessage" role="status">Đang tải chương trình Python…</span><button type="button" id="localRetry" class="ghost" hidden>Thử lại</button></div>\n</div>\n\n<main id="truMain"'),
        ('<script>\n// Attach the per-process token', '<script src="./local.js"></script>\n<script>\n// Attach the per-process token'),
        ("const module=new URLSearchParams(location.search).get('module');",
         "const requested=new URLSearchParams(location.search).get('module')||location.hash.slice(1);\n const module=['abc','ttt','tdm','adr'].includes(requested)?requested:'abc';"),
        ("refresh();load();guideRender();", ""),
        ("__PHARMADESK_TOKEN__", ""),
    ])
    (output / "index.html").write_text(html, encoding="utf-8")

    for name in ("local.js", "worker.mjs", "local.css"):
        shutil.copyfile(WEB / name, output / name)
    shutil.copyfile(ROOT / "docs" / "rules.json", output / "rules.json")
    fetch(SHEETJS + "dist/xlsx.full.min.js", output / "xlsx.full.min.js",
          "cc015130aa8521e7f088f88898eba949ccdcbfb38df0bd129b44b7273c3a6f41")
    fetch(SHEETJS + "LICENSE", output / "LICENSE-SheetJS.txt")
    fetch(f"https://raw.githubusercontent.com/pyodide/pyodide/{PYODIDE_VERSION}/LICENSE", runtime / "LICENSE.txt")
    beta = (ROOT / "docs" / "browser.html").read_text(encoding="utf-8")
    (output / "browser.html").write_text(beta.replace(SHEETJS + "dist/xlsx.full.min.js", "./xlsx.full.min.js"), encoding="utf-8")
    (output / ".nojekyll").touch()


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve())
