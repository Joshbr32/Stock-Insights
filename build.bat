@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  build.bat  —  Build StockInsights.exe for Raymond
REM
REM  Run this from the project root (the folder that contains main.py).
REM  The finished file will be at:  dist\StockInsights.exe
REM
REM  You keep working in PyCharm as normal.
REM  Only run this when you want to give Raymond a new version.
REM ─────────────────────────────────────────────────────────────────────────

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║       Stock Insights — Build Tool        ║
echo  ╚══════════════════════════════════════════╝
echo.

REM ── 1. Make sure PyInstaller is available ──────────────────────────────────
python -m pip install --quiet pyinstaller
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not install PyInstaller. Is Python/pip on your PATH?
    pause
    exit /b 1
)

REM ── 2. Clean previous build artefacts ─────────────────────────────────────
echo Cleaning previous build...
IF EXIST build   rmdir /s /q build
IF EXIST dist    rmdir /s /q dist

REM ── 3. Run PyInstaller ────────────────────────────────────────────────────
echo Building...
python -m PyInstaller stock_insights.spec --noconfirm
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed. See output above for details.
    pause
    exit /b 1
)

REM ── 4. Done ───────────────────────────────────────────────────────────────
echo.
echo  ┌─────────────────────────────────────────────────────┐
echo  │  Build succeeded!                                   │
echo  │  Give Raymond:  dist\StockInsights.exe              │
echo  └─────────────────────────────────────────────────────┘
echo.

REM Open the dist folder in Explorer so you can grab the file easily
start "" "%~dp0dist"

pause
