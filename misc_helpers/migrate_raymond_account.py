"""migrate_raymond_account.py — Move the 'Raymond' account from Josh's user to Raymond's user.

Run from the StockInsights project folder:
    python migrate_raymond_account.py

What it does:
  1. Logs in as Josh (admin) and reads all trades under the 'Raymond' account.
  2. Logs in as Raymond and uploads those trades to his own user.
  3. Asks for confirmation before deleting Raymond's trades from Josh's user.
"""

import json
import sys

SERVER_URL     = "http://192.168.0.149:8742"

JOSH_USERNAME  = "Josh"
JOSH_PASSWORD  = "secure_password_1"        # Josh's app password

RAYMOND_USERNAME = "Raymond"
RAYMOND_PASSWORD = "secure_password_2"      # Raymond's app password — change if different

ACCOUNT_TO_MOVE  = "Raymond"                # the account name to move

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)


def login(username: str, password: str) -> str:
    """Returns bearer token."""
    r = requests.post(
        f"{SERVER_URL}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if not r.ok:
        print(f"ERROR: Login failed for '{username}': {r.text}")
        sys.exit(1)
    print(f"  Logged in as '{username}'.")
    return r.json()["token"]


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


print("\n=== Move Raymond account: Josh -> Raymond ===\n")

# ---------------------------------------------------------------------------
# Step 1 — Log in as Josh and pull Raymond's trades
# ---------------------------------------------------------------------------

print("Step 1: Logging in as Josh and reading Raymond's trades...")
josh_token = login(JOSH_USERNAME, JOSH_PASSWORD)

r = requests.get(f"{SERVER_URL}/trades", headers=headers(josh_token), timeout=10)
r.raise_for_status()
all_josh_trades = r.json()

raymond_trades = [t for t in all_josh_trades if t.get("account") == ACCOUNT_TO_MOVE]
other_trades   = [t for t in all_josh_trades if t.get("account") != ACCOUNT_TO_MOVE]

if not raymond_trades:
    print(f"  No trades found under account '{ACCOUNT_TO_MOVE}' for Josh.")
    print("  Nothing to migrate.")
    sys.exit(0)

print(f"  Found {len(raymond_trades)} trade(s) under '{ACCOUNT_TO_MOVE}':")
for t in raymond_trades:
    status = "CLOSED" if t.get("sell_price") is not None else "OPEN"
    print(f"    {t['instrument']:6s}  {t['share_count']:>6} shares  "
          f"buy @ ${t['buy_price']:.2f}  {status}")

# ---------------------------------------------------------------------------
# Step 2 — Log in as Raymond and upload trades to his user
# ---------------------------------------------------------------------------

print(f"\nStep 2: Logging in as Raymond and uploading trades...")
raymond_token = login(RAYMOND_USERNAME, RAYMOND_PASSWORD)

# Ensure Raymond has a matching account name on his user
r = requests.get(f"{SERVER_URL}/accounts", headers=headers(raymond_token), timeout=10)
r.raise_for_status()
raymond_existing_accounts = {a["name"] for a in r.json()}

if ACCOUNT_TO_MOVE not in raymond_existing_accounts:
    print(f"  Creating account '{ACCOUNT_TO_MOVE}' on Raymond's user...")
    existing_list = list(raymond_existing_accounts)
    new_list = existing_list + [ACCOUNT_TO_MOVE]
    account_payload = [
        {"name": name, "goal_target": 500000.0,
         "goal_presets": [250000.0, 500000.0, 1000000.0], "position": i}
        for i, name in enumerate(new_list)
    ]
    r = requests.put(
        f"{SERVER_URL}/accounts",
        json={"accounts": account_payload},
        headers=headers(raymond_token), timeout=10,
    )
    r.raise_for_status()
    print(f"  Account '{ACCOUNT_TO_MOVE}' created for Raymond.")

# Check if Raymond already has trades for this account
r = requests.get(f"{SERVER_URL}/trades", headers=headers(raymond_token), timeout=10)
r.raise_for_status()
raymond_current_trades = [t for t in r.json() if t.get("account") == ACCOUNT_TO_MOVE]

if raymond_current_trades:
    print(f"\n  WARNING: Raymond already has {len(raymond_current_trades)} "
          f"trade(s) under '{ACCOUNT_TO_MOVE}'.")
    answer = input("  Overwrite? This will REPLACE Raymond's existing trades. (Y/N): ").strip().upper()
    if answer != "Y":
        print("  Aborted.")
        sys.exit(0)

# Build payload in server format
payload_trades = []
for t in raymond_trades:
    payload_trades.append({
        "instrument":  str(t.get("instrument", "")).strip().upper(),
        "share_count": int(t.get("share_count", 0) or 0),
        "buy_price":   float(t.get("buy_price", 0.0) or 0.0),
        "sell_price":  None if t.get("sell_price") is None else float(t["sell_price"]),
        "open_date":   t.get("open_date") or None,
        "close_date":  t.get("close_date") or None,
        "notes":       str(t.get("notes", "") or ""),
    })

r = requests.put(
    f"{SERVER_URL}/trades/{ACCOUNT_TO_MOVE}",
    json={"account_name": ACCOUNT_TO_MOVE, "trades": payload_trades},
    headers=headers(raymond_token), timeout=30,
)
r.raise_for_status()
print(f"  {len(payload_trades)} trade(s) uploaded to Raymond's user successfully.")

# ---------------------------------------------------------------------------
# Step 3 — Remove Raymond's trades from Josh's user
# ---------------------------------------------------------------------------

print(f"\nStep 3: Removing '{ACCOUNT_TO_MOVE}' trades from Josh's user...")
print(f"  Josh currently has {len(all_josh_trades)} total trade(s).")
print(f"  After removal he will have {len(other_trades)} trade(s).")

answer = input("  Confirm deletion of Raymond's trades from Josh? (Y/N): ").strip().upper()
if answer != "Y":
    print("  Skipped deletion — trades are now on BOTH users.")
    print("  Re-run and confirm deletion when ready.")
    sys.exit(0)

# Delete the Raymond account from Josh entirely
r = requests.get(f"{SERVER_URL}/accounts", headers=headers(josh_token), timeout=10)
r.raise_for_status()
josh_accounts = r.json()
josh_accounts_without_raymond = [
    {"name": a["name"], "goal_target": a["goal_target"],
     "goal_presets": json.loads(a["goal_presets"]) if isinstance(a["goal_presets"], str)
                     else a["goal_presets"],
     "position": a["position"]}
    for a in josh_accounts if a["name"] != ACCOUNT_TO_MOVE
]

r = requests.put(
    f"{SERVER_URL}/accounts",
    json={"accounts": josh_accounts_without_raymond},
    headers=headers(josh_token), timeout=10,
)
r.raise_for_status()
print(f"  Account '{ACCOUNT_TO_MOVE}' and its trades removed from Josh's user.")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

print(f"\n=== Migration complete ===")
print(f"  {len(raymond_trades)} trade(s) moved from Josh -> Raymond.")
print(f"  Restart Stock Insights to see the changes.")
