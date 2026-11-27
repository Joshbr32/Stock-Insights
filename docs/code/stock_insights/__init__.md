# stock_insights/__init__.py
**Purpose:** Package marker with a docstring and an `__all__` list of submodule names. It has no imports, so importing the package is free and Qt-less.
**Used by:** everything.  **Depends on:** nothing.

## Key types and functions
None. `__all__` lists modules, not symbols.

## Data and state
None.

## How to change it safely
Keep it import-free: `tests/` import `stock_insights.portfolio` without Qt, and any import here would break that. Update `__all__` when a module is added (not required for imports to work).

## Map
Lines 1-9.
