@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0" || goto :project_dir_error

if not exist ".venv\Scripts\python.exe" (
    echo Сначала запустите FIRST_RUN.bat
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "run_gui.py"
) else (
    ".venv\Scripts\python.exe" "run_gui.py"
)
exit /b %errorlevel%

:project_dir_error
echo ОШИБКА: не удалось перейти в папку проекта.
echo.
pause
exit /b 1
