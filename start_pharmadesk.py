import importlib.util
import subprocess
import sys
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

required = {
    "flask": "flask",
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    "docx": "python-docx",
    "pypdf": "pypdf",
    "reportlab": "reportlab",
    "PIL": "Pillow",
}
missing = [package for module, package in required.items()
           if importlib.util.find_spec(module) is None]

if missing:
    print("Dang cai thu vien con thieu:", ", ".join(missing))
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if result.returncode:
        print("Cai thu vien that bai. Kiem tra ket noi Internet/quyen cai dat.")
        input("Nhan Enter de dong...")
        raise SystemExit(result.returncode)

runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
