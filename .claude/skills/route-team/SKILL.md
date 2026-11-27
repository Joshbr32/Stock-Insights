---
name: route-team
description: Split a coding request into tasks, route each to Fable, Opus or Sonnet teammates for the best quality per token, coordinate them in one workspace, and make a single clean commit at the end. In this repository routing is ALWAYS ON - use it for every request that will change files (a feature, a fix, a refactor, tests, docs), not only when the user runs /route-team; it decides by itself when the work is small enough to do alone. Not for questions, reviews or read-only investigation, and never from inside a teammate or subagent.
---

> **Always on.** This skill runs for every request that changes files, typed with `/route-team` or not.
> Most requests are small: then step 2 sends it to "do it yourself", you say the routing in one line,
> skip steps 3-6 and go straight to the work, verification and commit rules. Only a request worth a
> team shows the plan and waits. A teammate or subagent never runs this skill.

# Route a request across the model team

You are the team lead, running on Opus. You plan, route, integrate, verify and commit. Teammates do
the implementation. The goal is the highest-quality result for the fewest tokens: every task goes to
the cheapest model that will get it right the first time - a redo on a cheaper model costs more than
doing it once on the right one.

Teammates:
- `fable-builder` (Fable) - most capable, about 2x Opus cost. Use sparingly, for work where a mistake is expensive.
- `opus-dev` (Opus) - the default for normal development.
- `sonnet-worker` (Sonnet) - cheap and fast, for well-defined mechanical work.

## 1. Check the starting state
- Run `git status`. If the working tree has uncommitted changes, stop and ask the user whether to commit, set aside (a WIP commit, never a bare `git stash`: the stash is shared with other worktrees) or include them. The final commit must contain only this request's work.
- Read README.md ("Repo layout", "Development", "Architecture notes") and enough of the code to understand what the request touches.

## Stock Insights rules every task inherits
Put these in every spawn prompt; teammates' agent files have them, but name the ones that bite for this task:
- `server/.env` and the `StockInsights` SQL Server database are live: no test, script or query against them, no write call to `si.coloniallawns.ca` / `COLONIAL_SERVER:8742`.
- `portfolio.py` <-> `pwa/js/portfolio.js` mirror 1:1: math changes go to one owner who changes both.
- Shell is PowerShell; desktop venv is `.venv`. Tests: `python -m pytest tests/ -q` (pure Python, no Qt). Compile check: `python -m compileall -q main.py stock_insights/ server/`.
- `build/`, `dist/`, `stock_insights.spec` are not touched unless the request is about the build.

## 2. Decide whether a team is worth it
A team costs far more tokens than one session (each teammate reloads context). Do not spawn teammates if:
- The whole request is small (roughly under an hour of human work, or under ~3 files) - do it yourself, or hand it to one teammate.
- The work is strictly sequential, with every step depending on the previous one.
Cheap wins that need no team: delegate a single mechanical chunk (tests, README, a rename) to one
`sonnet-worker` while you do the rest.
Say which option you picked and why in one line, e.g. "Routing: done here (two files, one fix)" or
"Routing: done here, tests to one sonnet-worker". On the solo path the starting-state check of step 1 is
just a look at `git status`: carry on when the tree is clean or holds only this conversation's own work.

## 3. Break the work into tasks
Each task must have:
- A clear deliverable and a definition of done (which tests pass, what the behaviour is).
- An explicit list of files that teammate owns. No file may be owned by two tasks.
- Shared hot spots get one owner. Other tasks that depend on them are marked blocked until that task is done. In this repo they are:
  - `server/server.py` (one file: one owner per request, however many endpoints change).
  - `stock_insights/portfolio.py` + `pwa/js/portfolio.js` (one owner for both copies).
  - `stock_insights/qml_bridge.py` (every QML view binds to its properties) and `stock_insights/main_window.py`.
  - `stock_insights/api_client.py` + `stock_insights/sync_queue.py` (the DataStore / offline-sync contract).
  - `stock_insights/theme.py` and `stock_insights/qml/qmldir`.
  - `pwa/js/app.js` (large; one owner) and `README.md`.
  - **Version numbers are the lead's**: `APP_VERSION` (`stock_insights/version.py`), `SERVER_VERSION` (`server/server.py`), `VERSION` (`pwa/sw.js`), `version.json`. No teammate edits them; the lead bumps them once in step 7.
- **Pre-digested context.** Teammates do not see this conversation, only the task text and their agent file. Give each the exact files and line ranges to start from, the relevant function/property names, and any decision you already made, so they do not spend tokens re-exploring what you already read. A good spawn prompt saves more tokens than a cheaper model does.

Aim for 2-6 tasks per teammate. Use at most one teammate per model.

## 4. Route each task

Send to fable-builder only when at least one applies:
- Refactor or change spanning several modules or more than ~5 files that must stay consistent
- Data-model, SQL schema or architecture decisions
- Concurrency or subtle-state logic: `FallbackDataStore` / `sync_queue.py` offline replay, `workers.py` / `_run_in_background` threading, the `/health` probe
- Portfolio math that must stay identical in `portfolio.py` and `portfolio.js` (P&L, drawdown, cost basis, goal projections)
- Auth, the Cloudflare Tunnel exposure, or anything security-sensitive in `server/server.py`
- A bug that already survived one serious fix attempt, or whose cause is unknown
- Work opus-dev reported back as too hard

Send to opus-dev (the default):
- A normal feature within one or two modules
- FastAPI endpoints, QML views or dialogs with real logic, `qml_bridge.py` properties
- PWA features in `pwa/js/app.js`
- Moderate bugs with a clear repro
- Reviewing fable-builder's changes when a second opinion is useful

Send to sonnet-worker:
- Unit tests under `tests/` for behaviour that already exists or is clearly specified
- README, docstrings and comments (the README's "why, not what" convention)
- Copy and label changes, small QML / `pwa/styles.css` styling and layout tweaks
- Renames, moving files, config edits (`requirements.txt`, `.env.example`), lint, format and type-error cleanup
- Fixtures, sample CSVs, boilerplate, icons via `pwa/make_icons.py`

When unsure between two tiers, pick the cheaper one. Teammates are told to hand work back if it is too hard.

## 5. Show the plan
Before spawning anyone, show the user a compact table: task, teammate, owned files, depends on, and one-line reason for each Fable task. Wait for approval, unless the user's request includes `--go`.

## 6. Run the team
- Create the tasks in the shared task list with their dependencies.
- Spawn each needed teammate by name using its agent type (fable-builder, opus-dev, sonnet-worker). Put the task details in the spawn prompt.
- Do not implement tasks yourself while teammates are working. Wait for their reports.
- If a teammate hands work back as too hard, reassign it one tier up. If two teammates need the same file, sequence them - never let them edit it at the same time.
- Follow-ups a teammate's report says a cheaper model could handle go to sonnet-worker, not back to the expensive teammate.
- When all tasks are done, ask teammates to shut down.

## 7. Integrate and verify
- `git status` and `git diff`: review all changes together. Check for overlapping edits, leftover debug code, stray `_*.py` test scripts or screenshots, and anything outside the plan.
- Bump every version the request touched: `VERSION` in `pwa/sw.js` for any change to `pwa/js/*.js`, `pwa/styles.css` or `pwa/index.html` (the pre-commit hook enforces it); `APP_VERSION` for desktop changes; `SERVER_VERSION` when endpoints or schema change.
- Run, from the repo root, whichever parts changed. Fix small issues yourself; send real problems back to the owning teammate:
  - `./.venv/Scripts/python.exe -m pytest tests/ -q` (when `tests/` exists)
  - `./.venv/Scripts/python.exe -m compileall -q main.py stock_insights/ server/`
  - An import check of every `stock_insights` module, for desktop changes.
  - `node --check pwa/js/<file>.js` for PWA changes.
- Tell the user what still needs a manual look: a QML change is not verified until the app has been run, a PWA change until a phone has picked up the new shell.

## 8. Commit once
- Stage only the files from this request.
- Make one commit for the request (or one per clearly separate feature if the user asked for several), with a clear message: a summary line, then a short body listing the main changes.
- Teammates never commit. Do not push unless the user asks. End the message with the commit attribution lines the session gives.
- Report to the user: what was done, which model did what, test results, and anything left open.
