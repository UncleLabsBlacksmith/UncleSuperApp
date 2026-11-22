@echo off
chcp 65001 >nul
setlocal
title Uncle Super App - Push to GitHub
cd /d "%~dp0"
set "REPO=https://github.com/UncleLabsBlacksmith/UncleSuperApp.git"
set "WEB=https://github.com/UncleLabsBlacksmith/UncleSuperApp"
set "MSG=%TEMP%\uncle_superapp_commit.txt"

where git >nul 2>nul
if errorlevel 1 goto :nogit

if exist ".git" goto :repo_ready
echo [1/5] สร้าง Git repository...
git init || goto :error
:repo_ready

rem --- ชื่อ/อีเมลสำหรับ commit (ถามครั้งเดียว) ---
git config user.email >nul 2>nul
if not errorlevel 1 goto :id_ready
echo.
set /p "GNAME=ชื่อที่แสดงใน commit (เช่น Uncle Engineer): "
set /p "GMAIL=อีเมลที่ใช้กับ GitHub: "
git config user.name "%GNAME%"
git config user.email "%GMAIL%"
:id_ready

echo [2/5] เพิ่มไฟล์ (ตาม .gitignore)...
git add -A || goto :error

rem --- กันพลาด: ห้ามมีไฟล์ความลับใน commit ---
git ls-files --cached --error-unmatch secret_key.txt >nul 2>nul
if not errorlevel 1 goto :secret
git ls-files --cached --error-unmatch db.sqlite3 >nul 2>nul
if not errorlevel 1 goto :secret

echo [3/5] Commit...
git diff --cached --quiet
if not errorlevel 1 goto :nothing_new
git rev-parse --verify HEAD >nul 2>nul
if errorlevel 1 goto :first_commit
set "NOTE="
set /p "NOTE=อธิบายสิ่งที่แก้ไขสั้นๆ (Enter = Update): "
if "%NOTE%"=="" set "NOTE=Update"
git commit -q -m "%NOTE%" || goto :error
goto :committed

:first_commit
> "%MSG%" echo Uncle Super App: All in One AI Generator
>>"%MSG%" echo.
>>"%MSG%" echo Django web app on OpenRouter: AI Chat, Image Generator + Gallery,
>>"%MSG%" echo Video Generator (Single / Series, background worker), Data Analyst and RAG.
>>"%MSG%" echo Developed by Uncle Engineer - https://uncle-engineer.com/
>>"%MSG%" echo.
>>"%MSG%" echo Co-Authored-By: Claude Opus 5.5 ^<noreply@anthropic.com^>
>>"%MSG%" echo Claude-Session: https://claude.ai/code/session_01Y86u35uZZKZugfnz8hgoGK
git commit -q -F "%MSG%" || goto :error
del "%MSG%" >nul 2>nul
goto :committed

:nothing_new
echo       ไม่มีไฟล์เปลี่ยนแปลงใหม่ - จะ push commit ที่มีอยู่
:committed
git branch -M main

echo [4/5] ตั้งค่า remote origin...
git remote get-url origin >nul 2>nul
if errorlevel 1 git remote add origin "%REPO%"
git remote set-url origin "%REPO%"

echo [5/5] Push ขึ้น GitHub... (ครั้งแรกจะมีหน้าต่างให้ล็อกอิน GitHub)
git push -u origin main || goto :pushfail

echo.
echo  สำเร็จ! เปิดดูที่ %WEB%
echo.
pause
goto :eof

:nogit
echo [!] ไม่พบ Git ในเครื่องนี้
echo     ติดตั้งจาก https://git-scm.com/download/win แล้วปิด/เปิดไฟล์นี้ใหม่
pause
exit /b 1

:secret
echo [!] พบ secret_key.txt หรือ db.sqlite3 ใน commit - หยุดการทำงานเพื่อความปลอดภัย
echo     ตรวจไฟล์ .gitignore แล้วรัน: git rm --cached secret_key.txt db.sqlite3
pause
exit /b 1

:pushfail
echo.
echo [!] Push ไม่สำเร็จ
echo     - ล็อกอินด้วยบัญชีที่มีสิทธิ์เขียน repo UncleLabsBlacksmith/UncleSuperApp
echo     - ถ้า GitHub มีไฟล์ที่เครื่องนี้ไม่มี เช่น สร้าง README บนเว็บ ให้รัน:
echo       git pull --rebase origin main   แล้วเปิดไฟล์นี้อีกครั้ง
pause
exit /b 1

:error
echo.
echo [!] เกิดข้อผิดพลาด ดูข้อความด้านบน
pause
exit /b 1
