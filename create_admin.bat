@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto :no_venv
echo สร้างบัญชีผู้ดูแลระบบ (Admin)
echo  - Email เว้นว่างได้ / ตอนพิมพ์รหัสผ่านจะไม่แสดงตัวอักษร เป็นเรื่องปกติ
echo.
".venv\Scripts\python.exe" manage.py createsuperuser
pause
goto :eof

:no_venv
echo [X] ยังไม่ได้ติดตั้งโปรแกรม - ดับเบิลคลิก run.bat ก่อน
echo     (run.bat จะติดตั้งทุกอย่างและถามสร้าง Admin ให้อัตโนมัติ)
pause
