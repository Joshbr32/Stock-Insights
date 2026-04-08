"""migrate_local_to_server.py — One-time migration of local QSettings trades to the SQL server.

Run from the StockInsights project folder:
    python migrate_local_to_server.py

What it does:
  1. Reads your old trades from QSettings (the local device backup).
  2. Logs into the server with your credentials.
  3. Pushes each account's trades to the server.
  4. Prints a summary so you can verify everything transferred correctly.

Your local QSettings data is NOT deleted — it stays as a backup.
"""

import json
import sys

# ---- Configuration — edit these before running ----
SERVER_URL = "http://192.168.0.149:8742"   # use local IP for migration (faster)
USERNAME   = "Josh"
PASSWORD   = "secure_password_1"           # your app login password
# ---------------------------------------------------

try:
    from PySide6.QtCore import QSettings
except ImportError:
    print("ERROR: PySide6 not installed. Run: pip install PySide6")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 1 — Read trades from QSettings
# ---------------------------------------------------------------------------

print("\n=== Stock Insights — Local → Server Migration ===\n")
print("Step 1: Reading trades from local QSettings...")

s = QSettings("StockInsights", "StocksGUI")
raw = s.value("portfolio/trades", "[]")

if isinstance(raw, list):
    trades_raw = raw
else:
    try:
        trades_raw = json.loads(raw)
    except Exception as exc:
        print(f"ERROR: Could not parse local trades: {exc}")
        sys.exit(1)

if not trades_raw:
    print("No local trades found in QSettings.")
    print("Nothing to migrate — your QSettings may already be empty,")
    print("or trades may have been saved under a different key.")
    sys.exit(0)

print(f"Found {len(trades_raw)} trade(s) in local storage.")

# Group by account
by_account: dict = {}
for trade in trades_raw:
    if not isinstance(trade, dict):
        continue
    account = str(trade.get("account") or "").strip() or "Default"
    by_account.setdefault(account, []).append(trade)

print(f"Accounts found: {list(by_account.keys())}")
for acct, trades in by_account.items():
    print(f"  {acct}: {len(trades)} trade(s)")


# ---------------------------------------------------------------------------
# Step 2 — Log into the server
# ---------------------------------------------------------------------------

print(f"\nStep 2: Logging into server at {SERVER_URL} as '{USERNAME}'...")

try:
    r = requests.post(
        f"{SERVER_URL}/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    token = r.json()["token"]
    print("  Login successful.")
except requests.exceptions.ConnectionError:
    print(f"ERROR: Cannot reach server at {SERVER_URL}")
    print("Make sure server.py is running and you're on the local network.")
    sys.exit(1)
except requests.exceptions.HTTPError as exc:
    print(f"ERROR: Login failed — {exc}")
    print("Check USERNAME and PASSWORD at the top of this script.")
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Step 3 — Ensure all accounts exist on the server
# ---------------------------------------------------------------------------

print("\nStep 3: Checking accounts on server...")

r = requests.get(f"{SERVER_URL}/accounts", headers=headers, timeout=10)
existing_accounts = {a["name"] for a in r.json()}
print(f"  Existing server accounts: {existing_accounts or '(none)'}")

all_accounts = list(by_account.keys())
missing = [a for a in all_accounts if a not in existing_accounts]

if missing:
    print(f"  Creating missing accounts: {missing}")
    combined = list(existing_accounts) + missing
    account_payload = [
        {"name": name, "goal_target": 500000.0,
         "goal_presets": [250000.0, 500000.0, 1000000.0], "position": i}
        for i, name in enumerate(combined)
    ]
    r = requests.put(
        f"{SERVER_URL}/accounts",
        json={"accounts": account_payload},
        headers=headers, timeout=10,
    )
    r.raise_for_status()
    print("  Accounts created.")
else:
    print("  All accounts already exist on server.")


# ---------------------------------------------------------------------------
# Step 4 — Push trades account by account
# ---------------------------------------------------------------------------

print("\nStep 4: Uploading trades...")

total_uploaded = 0
for account_name, trades in by_account.items():
    print(f"  Uploading {len(trades)} trade(s) for account '{account_name}'...")

    # Check if server already has trades for this account
    r = requests.get(f"{SERVER_URL}/trades", headers=headers, timeout=10)
    existing_trades = [t for t in r.json() if t.get("account") == account_name]

    if existing_trades:
        print(f"    WARNING: Server already has {len(existing_trades)} trade(s) for '{account_name}'.")
        answer = input(f"    Overwrite? This will REPLACE existing trades. (Y/N): ").strip().upper()
        if answer != "Y":
            print(f"    Skipped '{account_name}'.")
            continue

    # Convert QSettings format to server API format
    payload_trades = []
    for t in trades:
        payload_trades.append({
            "instrument":  str(t.get("instrument", "")).strip().upper(),
            "share_count": int(float(t.get("share_count", 0) or 0)),
            "buy_price":   float(t.get("buy_price", 0.0) or 0.0),
            "sell_price":  None if t.get("sell_price") in (None, "", "—", "-")
                           else float(t["sell_price"]),
            "open_date":   t.get("open_date") or None,
            "close_date":  t.get("close_date") or None,
            "notes":       str(t.get("notes", "") or ""),
        })

    r = requests.put(
        f"{SERVER_URL}/trades/{account_name}",
        json={"account_name": account_name, "trades": payload_trades},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    print(f"    Done — {len(payload_trades)} trade(s) uploaded.")
    total_uploaded += len(payload_trades)


# ---------------------------------------------------------------------------
# Step 5 — Migrate watchlist
# ---------------------------------------------------------------------------

print("\nStep 5: Migrating watchlist...")
watchlist_raw = s.value("watchlist/items", [])
if isinstance(watchlist_raw, str):
    try:
        watchlist_raw = json.loads(watchlist_raw)
    except Exception:
        watchlist_raw = []

if watchlist_raw:
    symbols = [str(t).upper() for t in watchlist_raw if str(t).strip()]
    r = requests.put(
        f"{SERVER_URL}/watchlist",
        json={"symbols": symbols},
        headers=headers, timeout=10,
    )
    r.raise_for_status()
    print(f"  Uploaded {len(symbols)} watchlist symbol(s): {symbols}")
else:
    print("  No watchlist items found locally.")


# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

print(f"\n=== Migration complete ===")
print(f"Trades uploaded : {total_uploaded}")
print(f"Your local QSettings backup is untouched.")
print(f"\nRestart Stock Insights and your trade history should appear.")
