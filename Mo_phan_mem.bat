@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo Khong tim thay Python 3. Vui long cai Python 3 va chon Add Python to PATH.
    pause
    exit /b 1
)
echo Dang mo Pharma Desk...
py -3 start_pharmadesk.py
if errorlevel 1 (
    echo Pharma Desk ket thuc do co loi. Xem thu muc Logs neu co.
    pause
)
