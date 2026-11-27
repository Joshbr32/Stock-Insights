# requirements.txt
**Purpose:** Desktop-client runtime dependencies (the server has its own `server/requirements.txt`).
**Used by:** `pip install -r requirements.txt`.  **Depends on:** n/a.

## Key types and functions
Direct: PySide6 (>=6.6,<7), requests, yfinance. Transitive pins are documented. `pandas-market-calendars` is optional and commented out; `portfolio.py` then falls back to weekday counting, which ignores holidays (the PWA must match).
`pytest` is needed to run `tests/` but is not listed here.

## Data and state
None.

## How to change it safely
Keep PySide6 below 7. Rebuild the exe after dependency changes.

## Map
Whole file, about 52 lines.
