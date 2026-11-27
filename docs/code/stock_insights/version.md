# stock_insights/version.py
**Purpose:** Single source of truth for `APP_VERSION` and `UPDATE_MANIFEST_URL`, plus release instructions in the docstring.
**Used by:** `update_checker.py` and anything sending a User-Agent.  **Depends on:** nothing.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `APP_VERSION` | str | "major.minor.patch"; compared numerically by `update_checker._parse_version`. Lead-controlled; do not bump casually. |
| `UPDATE_MANIFEST_URL` | str | Raw GitHub URL of `version.json` on branch `Portfolio`. |

## Data and state
Repo-root `version.json` is the hosted manifest; it must be kept in step manually.

## How to change it safely
Bump `APP_VERSION`, rebuild with `build.bat`, update `version.json`. No logic here.

## Map
Whole file, about 26 lines.
