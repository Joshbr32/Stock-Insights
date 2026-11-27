"""Tests for stock_insights.io_utils (CSV, backup/restore, auto-snapshot).

All writes go to pytest tmp_path; the auto-backup folder is redirected so the
real home directory is never touched.
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import date

import pytest

from stock_insights import io_utils as io
from stock_insights.portfolio import Trade, trade_to_dict


def _trades():
    return [
        Trade("aapl", 10, 100.0, 110.0, date(2024, 1, 2), date(2024, 1, 12),
              notes="line1\nline2", account="Main", tag="swing"),
        Trade("TSLA", 5, 200.0, None, date(2024, 2, 1), None, account="Main"),
        Trade("GME", 3, 20.0, 15.0, date(2024, 3, 1), date(2024, 3, 4),
              is_short=True, is_pending=False, account="Alt"),
        Trade("NVDA", 1, 50.0, is_pending=True, notes='has,comma "quote"'),
    ]


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def auto_dir(tmp_path, monkeypatch):
    d = tmp_path / "auto"
    monkeypatch.setattr(io, "_auto_backup_dir", lambda: d)
    return d


# ---------- CSV ----------

class TestCsv:
    def test_returns_row_count_and_header(self, tmp_path):
        p = tmp_path / "t.csv"
        assert io.export_trades_to_csv(_trades(), p) == 4
        with open(p, encoding="utf-8", newline="") as fh:
            assert next(csv.reader(fh)) == io.CSV_COLUMNS

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "a" / "b" / "t.csv"
        io.export_trades_to_csv([], p)
        assert p.exists()

    def test_empty_writes_header_only(self, tmp_path):
        p = tmp_path / "t.csv"
        assert io.export_trades_to_csv([], p) == 0
        assert _read_csv(p) == []

    def test_closed_long_row(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        r = _read_csv(p)[0]
        assert r["instrument"] == "AAPL" and r["side"] == "Long"
        assert r["qty"] == "10" and r["status"] == "CLOSED"
        assert r["buy_price"] == "100.00" and r["sell_price"] == "110.00"
        assert r["trade_profit"] == "100.00"
        assert r["open_date"] == "2024-01-02" and r["close_date"] == "2024-01-12"
        assert r["days_held"] == "10" and r["is_pending"] == "no"
        assert r["tag"] == "swing" and r["account"] == "Main"

    def test_newlines_in_notes_flattened(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        assert _read_csv(p)[0]["notes"] == "line1 line2"

    def test_open_trade_has_blank_sell_profit_days(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        r = _read_csv(p)[1]
        assert r["status"] == "OPEN"
        assert r["sell_price"] == "" and r["trade_profit"] == "" and r["close_date"] == ""
        assert r["days_held"] == ""

    def test_short_row(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        r = _read_csv(p)[2]
        assert r["side"] == "Short" and r["status"] == "COVERED"
        assert r["trade_profit"] == "15.00"

    def test_pending_row_and_quoting_roundtrip(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        r = _read_csv(p)[3]
        assert r["is_pending"] == "yes" and r["status"] == "WAITING"
        assert r["notes"] == 'has,comma "quote"'

    def test_accepts_generator_and_str_path(self, tmp_path):
        p = tmp_path / "t.csv"
        assert io.export_trades_to_csv((t for t in _trades()), str(p)) == 4

    def test_overwrites_existing_file(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        io.export_trades_to_csv(_trades()[:1], p)
        assert len(_read_csv(p)) == 1

    def test_no_blank_lines_between_rows(self, tmp_path):
        p = tmp_path / "t.csv"
        io.export_trades_to_csv(_trades(), p)
        text = p.read_bytes().decode("utf-8")
        assert "\n\n" not in text.replace("\r\n", "\n")

    def test_days_held_never_negative(self):
        assert io._days_held(date(2024, 1, 10), date(2024, 1, 1)) == "0"
        assert io._days_held(None, date(2024, 1, 1)) == ""


# ---------- build / write / read backup ----------

class TestBackup:
    def test_build_shape(self, fake_store_cls):
        s = fake_store_cls(trades=_trades())
        snap = io.build_backup(s)
        assert snap["schema_version"] == io.BACKUP_SCHEMA_VERSION
        assert snap["username"] == "tester"
        assert snap["accounts"] == ["Main"]
        assert snap["goal_targets"] == {"Main": 100_000.0}
        assert snap["goal_presets"] == {"Main": [1.0, 2.0]}
        assert snap["goal_group"] == {"shared_accounts": ["Main"], "shared_goal": 250_000.0}
        assert snap["watchlist"] == ["AAPL"]
        assert len(snap["trades"]) == 4
        assert "exported_at" in snap

    def test_build_is_json_serializable(self, fake_store_cls):
        json.dumps(io.build_backup(fake_store_cls(trades=_trades())))

    def test_build_survives_failing_store_calls(self, fake_store_cls):
        class Broken(fake_store_cls):
            def get_goal_target(self, name):
                raise RuntimeError("x")

            def get_goal_presets(self, name):
                raise RuntimeError("x")

            def get_goal_group(self):
                raise RuntimeError("x")

            def get_watchlist(self):
                raise RuntimeError("x")

            def get_all_trades(self):
                raise RuntimeError("x")

        snap = io.build_backup(Broken())
        assert snap["goal_targets"] == {"Main": 500_000.0}
        assert snap["goal_presets"] == {"Main": [250_000.0, 500_000.0, 1_000_000.0]}
        assert snap["goal_group"] == {"shared_accounts": [], "shared_goal": 500_000.0}
        assert snap["watchlist"] == [] and snap["trades"] == []
        assert io.validate_backup(snap) == []

    def test_missing_username_defaults_blank(self, fake_store_cls):
        s = fake_store_cls()
        s.user_info = {}
        assert io.build_backup(s)["username"] == ""

    def test_write_returns_path_and_creates_dirs(self, tmp_path, fake_store_cls):
        p = tmp_path / "x" / "y" / "b.json"
        assert io.write_backup(fake_store_cls(trades=_trades()), p) == p
        assert json.loads(p.read_text(encoding="utf-8"))["schema_version"] == 1

    def test_write_read_roundtrip_validates(self, tmp_path, fake_store_cls):
        p = tmp_path / "b.json"
        io.write_backup(fake_store_cls(trades=_trades()), str(p))
        snap = io.read_backup(p)
        assert io.validate_backup(snap) == []
        assert snap["trades"][0] == trade_to_dict(_trades()[0])

    def test_read_rejects_non_object(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text("[1,2]", encoding="utf-8")
        with pytest.raises(ValueError, match="not a JSON object"):
            io.read_backup(p)

    def test_read_rejects_wrong_schema(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        with pytest.raises(ValueError, match="not supported"):
            io.read_backup(p)

    def test_read_missing_schema_is_rejected(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            io.read_backup(p)

    def test_read_bad_json_raises_valueerror_subclass(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):  # json.JSONDecodeError subclasses ValueError
            io.read_backup(p)


# ---------- validate_backup ----------

def _good():
    return {
        "schema_version": 1,
        "accounts": ["Main"],
        "goal_targets": {"Main": 1000},
        "goal_presets": {"Main": [1, 2.5]},
        "goal_group": {"shared_accounts": [], "shared_goal": 5},
        "watchlist": ["AAPL"],
        "trades": [{"instrument": "AAPL", "share_count": 1, "buy_price": 2.0}],
    }


class TestValidate:
    def test_good(self):
        assert io.validate_backup(_good()) == []

    def test_not_dict(self):
        assert io.validate_backup([]) == ["Backup is not a JSON object."]

    @pytest.mark.parametrize("key", ["schema_version", "accounts", "goal_targets",
                                     "goal_presets", "goal_group", "watchlist", "trades"])
    def test_missing_key(self, key):
        snap = _good()
        del snap[key]
        errs = io.validate_backup(snap)
        assert any(key in e for e in errs)

    def test_wrong_type(self):
        snap = _good()
        snap["accounts"] = "Main"
        assert any("accounts" in e for e in io.validate_backup(snap))

    def test_bool_schema_version_rejected(self):
        snap = _good()
        snap["schema_version"] = True
        assert any("got bool" in e for e in io.validate_backup(snap))

    def test_schema_version_mismatch(self):
        snap = _good()
        snap["schema_version"] = 2
        assert any("schema version" in e for e in io.validate_backup(snap))

    def test_bad_account_names(self):
        snap = _good()
        snap["accounts"] = ["", 5, "ok"]
        assert len(io.validate_backup(snap)) == 2

    def test_bad_goal_target(self):
        snap = _good()
        snap["goal_targets"]["Main"] = "1000"
        assert any("Goal target" in e for e in io.validate_backup(snap))
        snap["goal_targets"]["Main"] = True
        assert any("Goal target" in e for e in io.validate_backup(snap))

    def test_bad_presets(self):
        snap = _good()
        snap["goal_presets"] = {"Main": "x", "B": [1, "2"]}
        errs = io.validate_backup(snap)
        assert any("not a list" in e for e in errs)
        assert any("preset #1" in e for e in errs)

    def test_bad_watchlist(self):
        snap = _good()
        snap["watchlist"] = ["A", 3]
        assert any("Watchlist entry #1" in e for e in io.validate_backup(snap))

    def test_bad_trades(self):
        snap = _good()
        snap["trades"] = [
            5,
            {"share_count": 1, "buy_price": 1},
            {"instrument": "  ", "share_count": 1, "buy_price": 1},
            {"instrument": "A", "buy_price": 1},
            {"instrument": "A", "share_count": "3", "buy_price": 1},
            {"instrument": "A", "share_count": 1, "buy_price": True},
        ]
        errs = io.validate_backup(snap)
        assert any("Trade #0 is not a JSON object" in e for e in errs)
        assert any("Trade #1 has no instrument" in e for e in errs)
        assert any("Trade #2 has no instrument" in e for e in errs)
        assert any("Trade #3 is missing share_count" in e for e in errs)
        assert any("Trade #4 field share_count is not numeric" in e for e in errs)
        assert any("Trade #5 field buy_price is not numeric" in e for e in errs)

    def test_extra_fields_ignored(self):
        snap = _good()
        snap["future_field"] = 1
        assert io.validate_backup(snap) == []


# ---------- apply_backup ----------

class TestApply:
    def test_full_restore(self, fake_store_cls):
        src = fake_store_cls(trades=_trades(), accounts=("Main", "Alt"))
        snap = io.build_backup(src)
        dst = fake_store_cls(accounts=())
        summary = io.apply_backup(dst, snap)
        assert dst.saved_accounts == ["Main", "Alt"]
        assert dst.saved_watchlist == ["AAPL"]
        assert dst.targets_set == {"Main": 100_000.0, "Alt": 100_000.0}
        assert dst.presets_set["Main"] == [1.0, 2.0]
        shared, goal, targets, presets = dst.group_call
        assert shared == ["Main", "Alt"] and goal == 250_000.0
        assert set(targets) == {"Main", "Alt"} and set(presets) == {"Main", "Alt"}
        assert summary == {"accounts": 2, "trades": 4, "watchlist": 1}

    def test_trades_grouped_by_account_with_fallback(self, fake_store_cls):
        snap = io.build_backup(fake_store_cls(trades=_trades(), accounts=("Main", "Alt")))
        dst = fake_store_cls(accounts=())
        io.apply_backup(dst, snap)
        assert {t.instrument for t in dst.saved_trades["Main"]} == {"AAPL", "TSLA", "NVDA"}
        assert [t.instrument for t in dst.saved_trades["Alt"]] == ["GME"]

    def test_accountless_trades_go_to_default_when_no_accounts(self, fake_store_cls):
        snap = _good()
        snap["accounts"] = []
        dst = fake_store_cls(accounts=())
        io.apply_backup(dst, snap)
        assert list(dst.saved_trades) == ["Default"]

    def test_empty_snapshot_touches_nothing_meaningful(self, fake_store_cls):
        dst = fake_store_cls(accounts=())
        assert io.apply_backup(dst, {}) == {"accounts": 0, "trades": 0, "watchlist": 0}
        assert dst.saved_accounts is None and dst.saved_watchlist is None
        assert dst.saved_trades == {}

    def test_store_errors_on_goals_and_trades_are_swallowed(self, fake_store_cls):
        class Flaky(fake_store_cls):
            def set_goal_target(self, *a):
                raise RuntimeError

            def set_goal_presets(self, *a):
                raise RuntimeError

            def set_goal_group(self, *a):
                raise RuntimeError

            def save_account_trades(self, *a):
                raise RuntimeError

        summary = io.apply_backup(Flaky(accounts=()), _good())
        assert summary["accounts"] == 1 and summary["trades"] == 1

    def test_zero_share_trades_are_dropped(self, fake_store_cls):
        snap = _good()
        snap["trades"].append({"instrument": "ZERO", "share_count": 0, "buy_price": 1})
        dst = fake_store_cls(accounts=())
        assert io.apply_backup(dst, snap)["trades"] == 1


# ---------- auto snapshots ----------

class TestAutoSnapshot:
    def test_writes_valid_file(self, auto_dir, fake_store_cls):
        p = io.write_auto_snapshot(fake_store_cls(trades=_trades()), "pre-restore")
        assert p is not None and p.parent == auto_dir
        assert p.name.startswith("pre-restore-") and p.suffix == ".json"
        assert io.validate_backup(io.read_backup(p)) == []

    def test_kind_is_slugified(self, auto_dir, fake_store_cls):
        p = io.write_auto_snapshot(fake_store_cls(), "../Evil Kind!")
        assert p.parent == auto_dir
        assert p.name.startswith("___evil_kind_-")

    def test_empty_kind_falls_back(self, auto_dir, fake_store_cls):
        p = io.write_auto_snapshot(fake_store_cls(), "")
        assert p.name.startswith("snapshot-")

    def test_prunes_to_keep_most_recent(self, auto_dir, fake_store_cls):
        auto_dir.mkdir(parents=True)
        now = time.time()
        for i in range(8):
            f = auto_dir / f"old-{i}.json"
            f.write_text("{}", encoding="utf-8")
            os.utime(f, (now - 1000 + i, now - 1000 + i))
        p = io.write_auto_snapshot(fake_store_cls())
        remaining = sorted(x.name for x in auto_dir.glob("*.json"))
        assert len(remaining) == io.AUTO_BACKUP_KEEP
        assert p.name in remaining
        # oldest ones were deleted, newest old ones survive
        assert "old-0.json" not in remaining and "old-7.json" in remaining

    def test_prune_ignores_non_json(self, tmp_path):
        (tmp_path / "keep.txt").write_text("x")
        for i in range(3):
            (tmp_path / f"{i}.json").write_text("{}")
        io._prune_auto_snapshots(tmp_path, 1)
        assert (tmp_path / "keep.txt").exists()
        assert len(list(tmp_path.glob("*.json"))) == 1

    def test_prune_missing_folder_is_silent(self, tmp_path):
        io._prune_auto_snapshots(tmp_path / "nope", 1)

    def test_failure_returns_none(self, auto_dir, fake_store_cls):
        class Boom(fake_store_cls):
            @property
            def user_info(self):
                raise RuntimeError("down")

            @user_info.setter
            def user_info(self, v):
                pass

        assert io.write_auto_snapshot(Boom()) is None

    def test_unwritable_dir_returns_none(self, tmp_path, monkeypatch, fake_store_cls):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setattr(io, "_auto_backup_dir", lambda: blocker / "sub")
        assert io.write_auto_snapshot(fake_store_cls()) is None

    def test_default_dir_under_home(self):
        p = io._auto_backup_dir()
        assert p.name == "auto_backups" and p.parent.name == ".stock_insights"
