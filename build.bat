@echo off
REM ================================================================
REM  CODETYPE - Build Script
REM  Packages the game into a standalone Windows .exe
REM  Requirements: Python 3.11+, pip install -r requirements.txt
REM ================================================================

echo.
echo  +==========================================+
echo        CODETYPE - PyInstaller Build
echo  +==========================================+
echo.

pip install -r requirements.txt

echo.
echo  Building CODETYPE.exe...
echo.

pyinstaller ^
    --onedir ^
    --windowed ^
    --name CODETYPE ^
    --add-data "data;data" ^
    --add-data "assets;assets" ^
    --add-data "database;database" ^
    --icon "assets\images\icon.ico" ^
    main.py

echo.
if %ERRORLEVEL% EQU 0 (
    echo  [ OK ] Build successful!
    echo         Output: dist\CODETYPE\CODETYPE.exe
) else (
    echo  [FAIL] Build failed. Check the output above.
)
echo.
pause
