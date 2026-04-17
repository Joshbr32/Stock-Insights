@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  build.bat  —  Build StockInsights.exe for Raymond
REM  Run this from the project root (the folder that contains main.py).
REM ─────────────────────────────────────────────────────────────────────────

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║       Stock Insights — Build Tool        ║
echo  ╚══════════════════════════════════════════╝
echo.

REM ── 1. Find the venv Python ───────────────────────────────────────────────
REM  PyCharm venvs are usually in .venv\  or  venv\  inside the project root.
REM  We try both locations. If neither exists we fall back to system python
REM  but warn the user first.

SET PYTHON=
IF EXIST ".venv\Scripts\python.exe"   SET PYTHON=.venv\Scripts\python.exe
IF EXIST "venv\Scripts\python.exe"    SET PYTHON=venv\Scripts\python.exe
IF EXIST ".venv\Scripts\python3.exe"  SET PYTHON=.venv\Scripts\python3.exe

IF "%PYTHON%"=="" (
    echo.
    echo  [WARNING] Could not find a venv in .venv\ or venv\
    echo  Using system python — PySide6 must be installed there.
    echo  It is strongly recommended to activate your PyCharm venv first.
    echo  Press Ctrl+C to cancel, or any key to continue anyway...
    pause >nul
    SET PYTHON=python
)

echo  Using Python: %PYTHON%
echo.

REM ── 2. Confirm PySide6 is visible from that Python ────────────────────────
%PYTHON% -c "import PySide6; print('  PySide6 found:', PySide6.__version__)"
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] PySide6 is NOT installed in: %PYTHON%
    echo.
    echo  Fix options:
    echo    A) Open PyCharm Terminal (which activates the venv) and run build.bat from there
    echo    B) Run this in your venv terminal:  pip install PySide6
    echo    C) Check that your venv path matches .venv\ or venv\ in the project root
    echo.
    pause
    exit /b 1
)

REM ── 3. Install / upgrade PyInstaller in the VENV ─────────────────────────
echo Installing/upgrading PyInstaller...
%PYTHON% -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pip failed.
    pause
    exit /b 1
)

REM ── 4. Clean previous build artefacts ─────────────────────────────────────
echo Cleaning previous build...
IF EXIST build   rmdir /s /q build
IF EXIST dist    rmdir /s /q dist

REM ── 5. Run PyInstaller using the VENV python ─────────────────────────────
echo Building...
%PYTHON% -m PyInstaller stock_insights.spec --noconfirm
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed. See output above for details.
    pause
    exit /b 1
)

REM ── 6. Done ───────────────────────────────────────────────────────────────
echo.
echo  ┌─────────────────────────────────────────────────────┐
echo  │  Build succeeded!                                   │
echo  │  Give Raymond:  dist\StockInsights.exe              │
echo  └─────────────────────────────────────────────────────┘
echo.

start "" "%~dp0dist"
pause
