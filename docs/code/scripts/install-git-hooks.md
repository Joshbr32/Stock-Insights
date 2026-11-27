# scripts/install-git-hooks.sh
**Purpose:** Copies `scripts/pre-commit-pwa-version-check.sh` to `.git/hooks/pre-commit`.
**Used by:** developer, run once (`bash scripts/install-git-hooks.sh`).  **Depends on:** git, sh.

## Key types and functions
Script: resolves the repo root via `git rev-parse`, checks the source hook exists, copies it (not a symlink, for Windows) and `chmod +x`.

## Data and state
Writes `.git/hooks/pre-commit` (overwrites any existing one).

## How to change it safely
Idempotent; re-run after editing the hook source.

## Map
Whole file, about 38 lines.
