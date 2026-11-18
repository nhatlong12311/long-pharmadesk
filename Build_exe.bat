@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0" || exit /b 1

set "APPNAME=PharmaDesk_V3_0"
set "OUT=dist\%APPNAME%"
set "PYVER="
set "STEP=Tim Python tuong thich"
echo [1/4] Kiem tra Python 64-bit...
for %%V in (3.12 3.13 3.11) do if not defined PYVER (
    py -%%V-64 -c "import sys" >nul 2>&1 && set "PYVER=%%V"
)
if not defined PYVER (
    echo Can Python 3.11, 3.12 hoac 3.13 ban 64-bit va trinh khoi chay py.
    echo Co the cai Python 3.12 64-bit tu python.org, sau do chay lai.
    goto :failed
)

set "BUILD_ENV=.pharmadesk-build-%PYVER%"
set "BUILD_PY=%BUILD_ENV%\Scripts\python.exe"
set "STEP=Tao moi truong build"
echo [2/4] Chuan bi moi truong build rieng voi Python %PYVER%...
if not exist "%BUILD_PY%" (
    py -%PYVER%-64 -m venv "%BUILD_ENV%"
    if errorlevel 1 goto :failed
)
set "STEP=Cai thu vien"
echo Dang kiem tra va cai thu vien. Pip se hien thi tien do ben duoi.
"%BUILD_PY%" -m pip install --disable-pip-version-check --timeout 20 --retries 2 --only-binary=:all: pyinstaller -r requirements.txt
if errorlevel 1 goto :failed
"%BUILD_PY%" -c "from PIL import Image, ImageFont, _imaging; from reportlab.pdfgen import canvas; print('Pillow / ReportLab OK')"
if errorlevel 1 goto :failed

set "STEP=Dong goi bang PyInstaller"
echo [3/4] Dong goi %APPNAME%. Cac dong INFO ben duoi la tien do build.
"%BUILD_PY%" -m PyInstaller --noconfirm --icon "PharmaDesk_GopPhieu.ico" --onedir --noupx --noconsole --name "%APPNAME%" ^
  --hidden-import xlrd --hidden-import openpyxl --hidden-import pandas ^
  --hidden-import PIL.ImageFont --hidden-import tkinter --hidden-import tkinter.filedialog ^
  --hidden-import docx --hidden-import lxml --hidden-import lxml.etree --hidden-import common --hidden-import abcven --hidden-import ttt --hidden-import tdm --hidden-import rpt_test --hidden-import adr --hidden-import pypdf --collect-all reportlab --collect-all PIL --collect-data docx ^
  --exclude-module matplotlib --exclude-module scipy ^
  --exclude-module IPython --exclude-module notebook --exclude-module jupyter ^
  --exclude-module pytest --exclude-module seaborn --exclude-module torch ^
  --exclude-module tensorflow --exclude-module pyarrow --exclude-module numexpr ^
  --exclude-module bottleneck --exclude-module numba --exclude-module sqlalchemy ^
  --exclude-module tables --exclude-module h5py ^
  --exclude-module pandas.tests --exclude-module numpy.tests --exclude-module numpy.f2py app.py
if errorlevel 1 goto :failed

set "STEP=Sao chep tep di kem"
echo [4/4] Sao chep giao dien, mau va tep du lieu...
for %%D in (ui ABC_VEN TUONG_TAC ADR) do (
    xcopy /e /i /y "%%D" "%OUT%\%%D"
    if errorlevel 1 goto :failed
)
for %%F in (Gop_va_sort_AZ.py Xuat_RPT_sang_XLS.vbs "Mau tong.xlsx" PharmaDesk_GopPhieu.ico README.md HUONG_DAN_TRU_TONG.txt) do (
    copy /y "%%~F" "%OUT%\"
    if errorlevel 1 goto :failed
)
for %%D in (RPT Excel_xuat) do if not exist "%OUT%\%%D\" (
    mkdir "%OUT%\%%D"
    if errorlevel 1 goto :failed
)
if not exist "%OUT%\%APPNAME%.exe" goto :failed
echo.
echo XONG. Chay "%OUT%\%APPNAME%.exe".
echo Khi chuyen may, hay copy ca thu muc "%OUT%".
if not defined CI (
    echo Nhan phim bat ky de dong cua so.
    pause >nul
)
exit /b 0

:failed
echo.
echo Build dung tai buoc: %STEP%.
echo Kiem tra thong bao loi ngay phia tren.
if not defined CI (
    echo Nhan phim bat ky de dong cua so.
    pause >nul
)
exit /b 1
