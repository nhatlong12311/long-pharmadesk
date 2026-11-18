@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo STEP 1: CLEAR OLD EXCEL EXPORTS AND EXPORT RPT
echo ===============================================
if exist "%SystemRoot%\SysWOW64\cscript.exe" (
  "%SystemRoot%\SysWOW64\cscript.exe" //nologo "Xuat_RPT_sang_XLS.vbs"
) else (
  cscript //nologo "Xuat_RPT_sang_XLS.vbs"
)
if errorlevel 1 (
  echo.
  echo Export step failed. Read the error above.
  pause
  exit /b 1
)
echo.
echo ===============================================
echo STEP 2: MERGE EXCEL AND SORT GROUP A-Z
echo ===============================================
py -3 "Gop_va_sort_AZ.py"
if errorlevel 1 (
  echo.
  echo Python failed or an error occurred during merge.
  echo If a library is missing, run Cai_dat_thu_vien.bat first.
  pause
  exit /b 1
)
echo.
echo DONE. Open Tong_hop_boi_hoan_tu_truc.xlsx and check the In sheet.
pause
