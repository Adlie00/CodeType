@echo off
REM ================================================================
REM  CODETYPE - Build Script
REM  Packages the game into a standalone Windows application
REM  Requirements: Python 3.11+, pip install -r requirements.txt
REM
REM  Output: dist\CODETYPE\CODETYPE.exe (a folder, not a single file:
REM  ship the whole CODETYPE folder).
REM
REM  The leaderboard database is NOT bundled: the game creates a
REM  fresh one on first run, and in a built game it lives in
REM  %APPDATA%\CODETYPE so updates never wipe a player's scores.
REM ================================================================

echo.
echo  +==========================================+
echo        CODETYPE - PyInstaller Build
echo  +==========================================+
echo.

pip install -r requirements.txt

REM Wipe previous output so a stale build can never be shipped by accident.
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo  Building CODETYPE.exe...
echo.

pyinstaller ^
    --onedir ^
    --windowed ^
    --clean ^
    --name CODETYPE ^
    --add-data "data;data" ^
    --add-data "assets;assets" ^
    --icon "assets\images\icon.ico" ^
    main.py

echo.
if %ERRORLEVEL% EQU 0 (
    echo  [ OK ] Build successful!
    echo         Output: dist\CODETYPE\CODETYPE.exe
    echo         Ship the whole dist\CODETYPE folder, not the exe alone.
) else (
    echo  [FAIL] Build failed. Check the output above.
)
echo.
pause
