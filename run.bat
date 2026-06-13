@echo off
cd /d "%~dp0"

set "CONDA_ROOT=F:\Anaconda"
set "PYTHON=%CONDA_ROOT%\python.exe"

if not exist "%PYTHON%" (
    echo Python not found at %PYTHON%
    pause
    exit /b 1
)

echo ========================================
echo    Light Novel Packer
echo ========================================
echo.

echo [1/2] Installing dependencies ...
"%PYTHON%" -m pip install -r "%~dp0requirements.txt" -q 2>nul

echo [2/2] Starting...
echo.
"%PYTHON%" "%~dp0main.py"

pause
