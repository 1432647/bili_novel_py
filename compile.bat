@echo off
cd /d "%~dp0"

set "PYTHON=F:\Anaconda\python.exe"
set "ANA=F:\Anaconda"

echo Installing PyInstaller...
"%PYTHON%" -m pip install pyinstaller -q 2>nul

echo Building EXE...
"%PYTHON%" -m PyInstaller --onefile --console --name bili_novel_packer ^
    --add-binary "%ANA%\DLLs\_ssl.pyd;DLLs" ^
    --add-binary "%ANA%\Library\bin\libssl-3-x64.dll;." ^
    --add-binary "%ANA%\Library\bin\libcrypto-3-x64.dll;." ^
    --hidden-import _ssl ^
    --hidden-import _socket ^
    --distpath build ^
    main.py

echo.
echo Done. EXE at build\bili_novel_packer.exe
pause
