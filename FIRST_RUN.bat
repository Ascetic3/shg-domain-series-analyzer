@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0" || goto :project_dir_error

set "PYTHON_CMD="
set "PYTHON_FOUND=0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_FOUND=1"
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python --version >nul 2>nul
        if not errorlevel 1 set "PYTHON_FOUND=1"
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    if "%PYTHON_FOUND%"=="1" (
        echo ОШИБКА: найденная версия Python ниже 3.10.
        echo Установите Python 3.10 или новее и снова запустите FIRST_RUN.bat.
    ) else (
        echo ОШИБКА: Python не найден.
        echo Установите Python 3.10 или новее и снова запустите FIRST_RUN.bat.
    )
    goto :failed
)

if not exist ".venv\Scripts\python.exe" (
    echo Создание виртуального окружения...
    %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 goto :venv_error
)

echo Обновление pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :pip_error

echo Установка приложения и необходимых зависимостей...
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :install_error

echo.
echo Установка завершена успешно.
echo При следующих запусках используйте START_SHG_ANALYZER.bat.
echo Запуск приложения...
".venv\Scripts\python.exe" "run_gui.py"
if errorlevel 1 goto :run_error
exit /b 0

:project_dir_error
echo ОШИБКА: не удалось перейти в папку проекта.
goto :failed

:venv_error
echo.
echo ОШИБКА: не удалось создать виртуальное окружение .venv.
goto :failed

:pip_error
echo.
echo ОШИБКА: не удалось обновить pip. Проверьте подключение к интернету.
goto :failed

:install_error
echo.
echo ОШИБКА: не удалось установить приложение и его зависимости.
goto :failed

:run_error
echo.
echo ОШИБКА: приложение завершилось с ошибкой.
goto :failed

:failed
echo.
pause
exit /b 1
