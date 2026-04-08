# stock_insights.spec
# ────────────────────────────────────────────────────────────────────────────
# PyInstaller spec file for Stock Insights.
#
# HOW TO BUILD
# ─────────────
#   1. Install PyInstaller into your venv once:
#          pip install pyinstaller
#
#   2. From the project root (the folder that contains main.py and the
#      stock_insights/ package), run:
#          pyinstaller stock_insights.spec
#
#      Or just double-click build.bat on Windows.
#
#   3. The finished .exe will be at:
#          dist\StockInsights.exe
#
#   4. Give Raymond that single file — he needs nothing else installed.
#
# YOU keep working in PyCharm on the source as normal.
# Only run build.bat when you want to ship Raymond a new version.
# ────────────────────────────────────────────────────────────────────────────

import sys
from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

block_cipher = None

a = Analysis(
    # Entry point — the script that runs your app
    scripts=["main.py"],

    # Extra directories PyInstaller should search for imports
    pathex=["."],

    # Binary dependencies (DLLs, .so files) — usually auto-detected
    binaries=[],

    # Non-Python data files to bundle
    # Add entries here if you have icons, images, or .json config files:
    #   datas=[("assets/icon.ico", "assets")],
    datas=[],

    # Hidden imports that PyInstaller's static analysis misses.
    # PySide6 + yfinance tend to use dynamic loading, so list them here.
    hiddenimports=[
        # PySide6 modules used at runtime
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",

        # yfinance / data stack
        "yfinance",
        "pandas",
        "numpy",
        "requests",
        "urllib3",
        "charset_normalizer",
        "certifi",
        "lxml",
        "appdirs",
        "frozendict",
        "multitasking",
        "platformdirs",
        "pytz",
        "dateutil",
        "six",

        # Our own package (ensures sub-modules are bundled)
        "stock_insights",
        "stock_insights.api_client",
        "stock_insights.connection_dialog",
        "stock_insights.data",
        "stock_insights.logging_utils",
        "stock_insights.main_window",
        "stock_insights.portfolio",
        "stock_insights.portfolio_tab",
        "stock_insights.settings_dialog",
        "stock_insights.sync_queue",
        "stock_insights.theme",
        "stock_insights.update_checker",
        "stock_insights.version",
        "stock_insights.widgets",
        "stock_insights.workers",
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Things we definitely don't need — reduces final .exe size
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="StockInsights",

    # ── Set to False while debugging to get a console window with error output
    # ── Set to True for the final release Raymond uses (no console popup)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # UPX compression shrinks the .exe — install UPX from https://upx.github.io
    upx_exclude=[],

    # windowed=True hides the black console window; set False to see print/log output
    console=False,

    # ── Optional: embed an icon (replace path with your .ico file)
    # icon="assets\\icon.ico",

    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,       # True = single .exe file (easiest to send to Raymond)
)
