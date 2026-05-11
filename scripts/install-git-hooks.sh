#!/usr/bin/env sh
# install-git-hooks.sh
# ────────────────────────────────────────────────────────────────────────
# Install the project's pre-commit hooks into .git/hooks/.
#
# Run from the project root:
#     bash scripts/install-git-hooks.sh
#
# Idempotent — re-running just refreshes the symlinks/copies.
# ────────────────────────────────────────────────────────────────────────

# Locate the repo root (works whether you run this from anywhere).
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "Not inside a git repository."; exit 1;
}

HOOK_SRC="$ROOT/scripts/pre-commit-pwa-version-check.sh"
HOOK_DST="$ROOT/.git/hooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
    echo "Source hook not found at $HOOK_SRC"
    exit 1
fi

mkdir -p "$ROOT/.git/hooks"
# Plain copy (not symlink) so the hook works on Windows too — Windows
# git can run shell scripts in hooks but doesn't always follow symlinks
# the same way Unix does.
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST" 2>/dev/null || true

echo "Installed pre-commit hook → $HOOK_DST"
echo ""
echo "It blocks commits that touch a PWA shell file (app.js, portfolio.js,"
echo "styles.css, index.html) without bumping VERSION in pwa/sw.js."
echo ""
echo "To bypass for a single commit:"
echo "    git commit --no-verify"
