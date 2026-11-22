@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Uncle Super App
cd /d "%~dp0"
set "HERE=%~dp0"
set "PY_URL=https://www.python.org/downloads/release/python-3150/"

echo ============================================================
echo    Uncle Super App   -   Developed by Uncle Engineer
echo    https://uncle-engineer.com/
echo ============================================================
echo.

rem ------------------------------------------------------------
rem  0) ตรวจว่าแตกไฟล์ ZIP แล้ว และอยู่ในโฟลเดอร์โปรเจกต์
rem ------------------------------------------------------------
if /i not "%HERE:\AppData\Local\Temp\=%"=="%HERE%" goto :in_zip
if not exist "manage.py" goto :wrong_folder

rem ------------------------------------------------------------
rem  1) หา Python (ต้องเป็น 3.10 ขึ้นไป แนะนำ 3.15)
rem ------------------------------------------------------------
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto :no_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul || goto :old_python
for /f "delims=" %%v in ('%PY% -c "import platform; print(platform.python_version())"') do set "PYVER=%%v"
echo [OK] พบ Python %PYVER%
if "%PY%"=="py -3" echo      หมายเหตุ: ใช้ผ่านคำสั่ง py เพราะ python ยังไม่อยู่ใน PATH - ใช้งานได้ปกติ

rem ------------------------------------------------------------
rem  2) Virtual environment (.venv) - สร้างอัตโนมัติครั้งแรก
rem ------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" goto :make_venv
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul && goto :venv_ok
echo [!] .venv เดิมใช้งานไม่ได้ เช่น ย้ายโฟลเดอร์ หรือถอน/อัปเดต Python - กำลังสร้างใหม่...
rmdir /s /q ".venv" 2>nul
if exist ".venv" goto :venv_locked
:make_venv
echo [1/4] สร้าง virtual environment (.venv) ... ทำครั้งแรกครั้งเดียว
%PY% -m venv .venv
if errorlevel 1 goto :venv_fail
if not exist ".venv\Scripts\python.exe" goto :venv_fail
:venv_ok
set "VPY=%HERE%.venv\Scripts\python.exe"
echo [OK] virtual environment พร้อม

rem ------------------------------------------------------------
rem  3) ติดตั้งไลบรารีจาก requirements.txt
rem ------------------------------------------------------------
"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 "%VPY%" -m ensurepip --upgrade >nul 2>nul
"%VPY%" -c "import django, requests, cryptography, pypdf, openpyxl, imageio_ffmpeg" >nul 2>nul
if errorlevel 1 goto :pip_full
echo [2/4] ตรวจสอบไลบรารี...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_fail
goto :pip_ok
:pip_full
echo [2/4] ติดตั้งไลบรารี (Django, ffmpeg ฯลฯ) ... ครั้งแรกใช้เวลา 1-5 นาที ขึ้นกับความเร็วเน็ต
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip >nul 2>nul
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_fail
:pip_ok
echo [OK] ไลบรารีครบ

rem ------------------------------------------------------------
rem  4) ฐานข้อมูล
rem ------------------------------------------------------------
echo [3/4] เตรียมฐานข้อมูล...
"%VPY%" manage.py migrate --noinput -v 0
if errorlevel 1 goto :migrate_fail
echo [OK] ฐานข้อมูลพร้อม

rem ------------------------------------------------------------
rem  5) บัญชี Admin (ถ้ายังไม่มี ให้สร้างตอนนี้)
rem ------------------------------------------------------------
"%VPY%" manage.py shell -c "import sys; from django.contrib.auth import get_user_model as U; sys.exit(0 if U().objects.filter(is_superuser=True).exists() else 3)" >nul 2>nul
if not errorlevel 3 goto :admin_ok
echo.
echo ------------------------------------------------------------
echo  ยังไม่มีบัญชีผู้ดูแลระบบ (Admin) - สร้างตอนนี้เลย
echo  - Username : ชื่อผู้ใช้ภาษาอังกฤษ เช่น admin
echo  - Email    : เว้นว่างได้ กด Enter ผ่านไป
echo  - Password : ตอนพิมพ์รหัสผ่านจะไม่แสดงตัวอักษร เป็นเรื่องปกติ
echo ------------------------------------------------------------
"%VPY%" manage.py createsuperuser
if errorlevel 1 echo [!] ยังไม่ได้สร้าง Admin - สร้างภายหลังได้ด้วย create_admin.bat
:admin_ok

rem ------------------------------------------------------------
rem  6) เปิด server
rem ------------------------------------------------------------
set "PORT=8000"
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul && set "PORT=8001"
if "%PORT%"=="8001" echo [!] Port 8000 ถูกใช้อยู่ อาจเปิด server ซ้อนไว้อีกหน้าต่าง - ใช้ Port 8001 แทน
set "LANIP="
for /f "delims=" %%i in ('.venv\Scripts\python.exe -c "import socket;s=socket.socket(2,2);s.connect((socket.inet_ntoa(bytes([8,8,8,8])),80));print(s.getsockname()[0])" 2^>nul') do set "LANIP=%%i"

echo.
echo [4/4] เปิดใช้งาน
echo ============================================================
echo    เปิดเบราว์เซอร์ไปที่   http://127.0.0.1:%PORT%
if defined LANIP echo    มือถือ / เครื่องอื่นในวง LAN:  http://%LANIP%:%PORT%
echo    ปิดโปรแกรม: กด Ctrl+C หรือปิดหน้าต่างนี้
echo    ห้ามปิดหน้าต่างนี้ระหว่างใช้งาน (วิดีโอสร้างอยู่เบื้องหลังที่นี่)
echo ============================================================
echo.
if not defined NO_BROWSER start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:%PORT%/"
"%VPY%" manage.py runserver 0.0.0.0:%PORT%
if errorlevel 1 goto :server_fail
goto :eof


rem ============================================================
rem  ข้อความแนะนำเมื่อเกิดปัญหา
rem ============================================================
:no_python
echo [X] ไม่พบ Python ในเครื่องนี้
echo.
call :python_help
goto :end_fail

:old_python
for /f "delims=" %%v in ('%PY% -c "import platform; print(platform.python_version())"') do set "PYVER=%%v"
echo [X] Python ในเครื่องเป็นเวอร์ชัน %PYVER% ซึ่งเก่าเกินไป - ต้องใช้ 3.10 ขึ้นไป
echo.
call :python_help
goto :end_fail

:python_help
echo ------------------------------------------------------------
echo  วิธีติดตั้ง Python - ทำครั้งเดียว
echo ------------------------------------------------------------
echo  1. ดาวน์โหลด Python 3.15 จาก
echo       %PY_URL%
echo     เลื่อนลงไปที่ Files แล้วเลือก "Windows installer (64-bit)"
echo.
echo  2. เปิดไฟล์ที่ดาวน์โหลด หน้าต่างแรกให้ติ๊ก ช่องด้านล่าง
echo       [x] Add python.exe to PATH      ^<-- สำคัญมาก ห้ามลืม
echo     แล้วกด "Install Now" รอจนขึ้น Setup was successful
echo.
echo  3. ปิดหน้าต่างนี้ แล้วดับเบิลคลิก run.bat ใหม่อีกครั้ง
echo     โปรแกรมจะติดตั้งส่วนที่เหลือให้อัตโนมัติ
echo.
echo  * ถ้าติดตั้งแล้วยังขึ้นข้อความนี้ ให้ Restart เครื่อง 1 ครั้ง
echo  * ถ้าลืมติ๊ก Add to PATH: เปิดไฟล์ติดตั้งอีกครั้ง เลือก Modify
echo    กด Next แล้วติ๊ก "Add Python to environment variables" กด Install
echo ------------------------------------------------------------
echo.
choice /c YN /m "เปิดหน้าดาวน์โหลด Python ให้เลยไหม (Y = เปิด, N = ไม่)"
if not errorlevel 2 start "" "%PY_URL%"
exit /b 0

:in_zip
echo [X] กำลังรันจากในไฟล์ ZIP
echo     คลิกขวาที่ไฟล์ ZIP เลือก "Extract All..." (แตกไฟล์ทั้งหมด)
echo     แล้วเข้าไปในโฟลเดอร์ที่แตกออกมา ดับเบิลคลิก run.bat อีกครั้ง
goto :end_fail

:wrong_folder
echo [X] ไม่พบไฟล์ manage.py ในโฟลเดอร์นี้
echo     run.bat ต้องอยู่โฟลเดอร์เดียวกับ manage.py
echo     ถ้าแตกไฟล์ ZIP แล้วได้โฟลเดอร์ซ้อนกัน ให้เข้าไปอีกชั้นแล้วรัน run.bat ในนั้น
goto :end_fail

:venv_locked
echo [X] ลบ .venv เดิมไม่ได้ เพราะมีโปรแกรมใช้งานอยู่
echo     ปิดหน้าต่าง Uncle Super App / VS Code ที่เปิดอยู่ แล้วรัน run.bat ใหม่
echo     หรือลบโฟลเดอร์ .venv เองแล้วรันใหม่
goto :end_fail

:venv_fail
echo [X] สร้าง virtual environment ไม่สำเร็จ
echo     - ลองติดตั้ง Python ใหม่จาก %PY_URL%
echo       และติ๊ก "Add python.exe to PATH" ตอนติดตั้ง
echo     - ถ้าโฟลเดอร์อยู่ใน OneDrive หรือโฟลเดอร์ที่ห้ามเขียน ให้ย้ายไปไว้ที่อื่น เช่น C:\UncleSuperApp
goto :end_fail

:pip_fail
echo.
echo [X] ติดตั้งไลบรารีไม่สำเร็จ
echo     - ตรวจว่าเชื่อมต่ออินเทอร์เน็ตอยู่ แล้วรัน run.bat ใหม่ ระบบจะติดตั้งต่อจากเดิม
echo     - ถ้าใช้เน็ตบริษัท/มีไฟร์วอลล์ อาจต้องให้ IT อนุญาต pypi.org และ files.pythonhosted.org
echo     - ถ้ายังไม่ได้ ลบโฟลเดอร์ .venv แล้วรัน run.bat ใหม่
goto :end_fail

:migrate_fail
echo.
echo [X] เตรียมฐานข้อมูลไม่สำเร็จ ดูข้อความด้านบน
echo     - ถ้าขึ้น "database is locked" ให้ปิด server ที่เปิดซ้อนอยู่อีกหน้าต่าง แล้วรันใหม่
goto :end_fail

:server_fail
echo.
echo [X] Server หยุดทำงานเพราะเกิดข้อผิดพลาด ดูข้อความด้านบน
goto :end_fail

:end_fail
echo.
pause
exit /b 1
