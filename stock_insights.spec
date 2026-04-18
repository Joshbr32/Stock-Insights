# stock_insights.spec
# ────────────────────────────────────────────────────────────────────────────
# PyInstaller spec file for Stock Insights.
#
# HOW TO BUILD
# ─────────────
#   1. Make sure your venv has the latest hooks support:
#          pip install --upgrade pyinstaller pyinstaller-hooks-contrib
#
#   2. From the project root (the folder that contains main.py), run:
#          pyinstaller stock_insights.spec --noconfirm
#      Or just double-click build.bat.
#
#   3. The finished .exe will be at:  dist\StockInsights.exe
#
#   4. Give Raymond that single file — he needs nothing else installed.
#
# FIX: "PySide6 is not installed" error
# ───────────────────────────────────────
# PySide6 ships hundreds of DLLs and Qt plugins that PyInstaller's static
# analysis cannot detect on its own.  The fix is to use collect_all() which
# force-bundles every file PySide6 installed into your venv — binaries,
# data files, and hidden imports alike.  This is the only reliable approach.
# ────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path
from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Collect EVERYTHING from PySide6 (the critical fix) ───────────────────────
pyside6_datas,    pyside6_binaries,    pyside6_hiddenimports    = collect_all("PySide6")

# ── Collect yfinance and its data files ──────────────────────────────────────
yfinance_datas,   yfinance_binaries,   yfinance_hiddenimports   = collect_all("yfinance")

# ── Collect pandas (has .pyd extensions and data files) ──────────────────────
pandas_datas,     pandas_binaries,     pandas_hiddenimports     = collect_all("pandas")

# ── Collect requests / certifi (SSL certs must travel with the .exe) ─────────
certifi_datas,    certifi_binaries,    certifi_hiddenimports    = collect_all("certifi")
requests_datas,   requests_binaries,   requests_hiddenimports   = collect_all("requests")

# ── Bundle our own QML scene + reusable components ───────────────────────────
qml_files = [
    (str(p), "stock_insights/qml")
    for p in Path("stock_insights/qml").glob("*")
    if p.is_file()
]

# ── Combine everything ────────────────────────────────────────────────────────
all_datas = (
    pyside6_datas
    + yfinance_datas
    + pandas_datas
    + certifi_datas
    + requests_datas
    + qml_files
)

all_binaries = (
    pyside6_binaries
    + yfinance_binaries
    + pandas_binaries
    + certifi_binaries
    + requests_binaries
)

all_hiddenimports = (
    pyside6_hiddenimports
    + yfinance_hiddenimports
    + pandas_hiddenimports
    + certifi_hiddenimports
    + requests_hiddenimports
    + collect_submodules("PySide6")
    + collect_submodules("stock_insights")
    + [
        # Qt platform plugin — required for any window to appear on Windows
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtPrintSupport",
        "PySide6.QtSvg",
        "PySide6.QtXml",
        # QML / Qt Quick runtime — required by the QQuickWidget central area
        "PySide6.QtQml",
        "PySide6.QtQmlModels",
        "PySide6.QtQmlWorkerScript",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickLayouts",
        "PySide6.QtQuickTemplates2",
        "PySide6.QtOpenGL",

        # yfinance internals loaded at runtime
        "yfinance",
        "yfinance.base",
        "yfinance.ticker",
        "yfinance.multi",
        "yfinance.scrapers",
        "yfinance.utils",

        # Data/networking stack
        "urllib3",
        "urllib3.util.retry",
        "charset_normalizer",
        "lxml",
        "lxml.etree",
        "lxml._elementpath",
        "appdirs",
        "frozendict",
        "multitasking",
        "platformdirs",
        "pytz",
        "dateutil",
        "dateutil.parser",
        "six",
        "bs4",

        # Our own package
        "stock_insights",
        "stock_insights.api_client",
        "stock_insights.connection_dialog",
        "stock_insights.data",
        "stock_insights.logging_utils",
        "stock_insights.main_window",
        "stock_insights.portfolio",
        "stock_insights.portfolio_tab",
        "stock_insights.qml_bridge",
        "stock_insights.settings_dialog",
        "stock_insights.sync_queue",
        "stock_insights.theme",
        "stock_insights.update_checker",
        "stock_insights.version",
        "stock_insights.widgets",
        "stock_insights.workers",
    ]
)

a = Analysis(
    scripts=["main.py"],
    pathex=["."],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        # Qt modules we definitely don't use (shrinks the .exe)
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        # NOTE: PySide6.QtQuick / QtQuickWidgets are required by the QML
        # main scene — must NOT be excluded.  QtQuick3D is fine to drop.
        "PySide6.QtQuick3D",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
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
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,

    # UPX reduces file size but can trigger false-positive antivirus alerts.
    # If Raymond's antivirus flags the .exe, set upx=False and rebuild.
    upx=False,
    upx_exclude=[],

    # console=False hides the black terminal window (release mode)
    # Temporarily set console=True if you need to see error output
    console=False,

    # icon="assets\\icon.ico",

    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
