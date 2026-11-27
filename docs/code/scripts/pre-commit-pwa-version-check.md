# scripts/pre-commit-pwa-version-check.sh
**Purpose:** Pre-commit guard that blocks commits touching PWA shell files without also touching `pwa/sw.js` (the VERSION bump).
**Used by:** installed as `.git/hooks/pre-commit`.  **Depends on:** git, grep.

## Key types and functions
The pattern `^pwa/(js/(app|api|portfolio)\.js|styles\.css|index\.html)$` is the shell-file list. Exit 0 if no shell file is staged or sw.js is also staged; otherwise print guidance and exit 1. It checks only that sw.js is staged, not that VERSION changed.

## Data and state
None.

## How to change it safely
Add newly cached shell files (for example `pwa/js/ui.js`, which is not in the pattern yet) to the regex. Bypass with `git commit --no-verify`.

## Map
Pattern line 25; checks 28-45; message 47-end.
