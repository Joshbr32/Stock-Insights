"""Shared pytest setup: make the repo root importable and provide a fake store.

No test needs a Qt event loop or the internet. test_sync.py and test_controller.py
use throwaway HTTP servers on 127.0.0.1; test_server.py fakes pyodbc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeStore:
    """Minimal in-memory stand-in for the DataStore interface used by io_utils."""

    def __init__(self, trades=None, accounts=("Main",), watchlist=("AAPL",)):
        self.user_info = {"username": "tester"}
        self._accounts = list(accounts)
        self._trades = list(trades or [])
        self._watchlist = list(watchlist)
        self._targets = {a: 100_000.0 for a in self._accounts}
        self._presets = {a: [1.0, 2.0] for a in self._accounts}
        self._group = (list(self._accounts), 250_000.0)
        # Records of what apply_backup wrote.
        self.saved_accounts = None
        self.saved_watchlist = None
        self.saved_trades = {}
        self.group_call = None
        self.targets_set = {}
        self.presets_set = {}

    def get_account_names(self):
        return list(self._accounts)

    def get_goal_target(self, name):
        return self._targets[name]

    def get_goal_presets(self, name):
        return self._presets[name]

    def get_goal_group(self):
        return self._group

    def get_watchlist(self):
        return list(self._watchlist)

    def get_all_trades(self):
        return list(self._trades)

    # write side
    def save_accounts(self, accounts):
        self.saved_accounts = list(accounts)

    def set_goal_target(self, name, value):
        self.targets_set[name] = value

    def set_goal_presets(self, name, presets):
        self.presets_set[name] = presets

    def set_goal_group(self, shared, goal, targets, presets):
        self.group_call = (shared, goal, targets, presets)

    def save_watchlist(self, wl):
        self.saved_watchlist = list(wl)

    def save_account_trades(self, name, trades):
        self.saved_trades[name] = list(trades)


@pytest.fixture
def fake_store_cls():
    return FakeStore
