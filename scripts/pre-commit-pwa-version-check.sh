#!/usr/bin/env sh
# pre-commit-pwa-version-check.sh
# ────────────────────────────────────────────────────────────────────────
# Block commits that touch a PWA shell file (app.js / portfolio.js /
# styles.css / index.html) without bumping `VERSION` in pwa/sw.js.
#
# Why this exists:
#   The service worker caches the shell aggressively. Phones keep serving
#   the previous app.js until VERSION changes, regardless of what the
#   server is handing out — so forgetting to bump it means deployed
#   updates silently never reach users.
#
# How to install:
#   bash scripts/install-git-hooks.sh           (preferred)
#   — OR —
#   cp scripts/pre-commit-pwa-version-check.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Bypass (use sparingly, e.g. when you're committing a non-shell change
# that pre-commit miscategorized):
#   git commit --no-verify
# ────────────────────────────────────────────────────────────────────────

# Files whose changes require a sw.js VERSION bump.
SHELL_FILES_PATTERN='^pwa/(js/(app|api|portfolio)\.js|styles\.css|index\.html)$'

# What's about to be committed (staged changes only).
staged_files=$(git diff --cached --name-only)

shell_changed=$(printf '%s\n' "$staged_files" | grep -E "$SHELL_FILES_PATTERN" || true)
sw_changed=$(printf '%s\n' "$staged_files" | grep -E '^pwa/sw\.js$' || true)

# No shell file changed → nothing to check.
if [ -z "$shell_changed" ]; then
    exit 0
fi

# Shell file changed AND sw.js was also touched → assume the dev did the
# right thing. (We can't verify the actual VERSION value changed without
# parsing sw.js, but bumping it is exactly what we wanted them to do.)
if [ -n "$sw_changed" ]; then
    exit 0
fi

# Shell changed, sw.js didn't → block.
echo ""
echo "──────────────────────────────────────────────────────────────────────"
echo "  PWA shell file changed but pwa/sw.js VERSION wasn't bumped."
echo ""
echo "  Changed shell file(s):"
printf '%s\n' "$shell_changed" | sed 's/^/    • /'
echo ""
echo "  Bump the VERSION constant in pwa/sw.js (e.g. v3 → v4) so phones"
echo "  pick up the new shell. Without the bump, the service worker"
echo "  keeps serving the cached old app.js forever."
echo ""
echo "  To bypass for a non-deploying change:"
echo "    git commit --no-verify"
echo "──────────────────────────────────────────────────────────────────────"
echo ""
exit 1
