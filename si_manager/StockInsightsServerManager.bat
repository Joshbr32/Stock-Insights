@echo off
rem Starts the Stock Insights Server Manager (python -m si_manager) without a console window.
rem Uses the repository's .venv when there is one (it has PySide6), else pythonw on PATH.
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m si_manager
) else (
    start "" pythonw -m si_manager
)
