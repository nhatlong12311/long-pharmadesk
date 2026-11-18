@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 (echo Cai dat that bai. & pause & exit /b 1)
echo Cai dat hoan tat.
pause
