"""Tests for stock_insights.portfolio (pure Python, no Qt, no network)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from stock_insights import portfolio as pf
from stock_insights.portfolio import (
    Holding,
    Trade,
    compute_goal_progress,
    compute_holdings_from_trades,
    compute_portfolio,
    compute_realized_pl_by_symbol,
    compute_trade_analytics,
    compute_trade_rows,
    filter_trades_by_date_range_with_orig_index,
    parse_date,
    solve_buy_mark_for_target_avg,
    trade_from_dict,
    trade_to_dict,
    trades_from_json,
    trades_to_json,
)


def closed(sym="AAA", qty=10, buy=10.0, sell=12.0, o=date(2024, 1, 2), c=date(2024, 1, 9), **kw):
    return Trade(sym, qty, buy, sell, o, c, **kw)


def open_(sym="AAA", qty=10, buy=10.0, o=date(2024, 1, 2), **kw):
    return Trade(sym, qty, buy, None, o, None, **kw)


# ---------- Trade model ----------

class TestTrade:
    def test_long_profit(self):
        assert closed(buy=10, sell=12, qty=10).trade_profit == pytest.approx(20.0)

    def test_short_profit(self):
        t = closed(buy=12, sell=10, qty=10, is_short=True)
        assert t.trade_profit == pytest.approx(20.0)

    def test_short_loss(self):
        t = closed(buy=10, sell=12, qty=5, is_short=True)
        assert t.trade_profit == pytest.approx(-10.0)

    def test_open_has_no_profit(self):
        assert open_().trade_profit is None

    def test_sell_without_close_date_is_not_closed(self):
        t = Trade("A", 1, 1.0, sell_price=2.0, close_date=None)
        assert not t.is_closed and t.trade_profit is None

    def test_cost_basis(self):
        assert open_(qty=4, buy=2.5).cost_basis == pytest.approx(10.0)

    @pytest.mark.parametrize("trade,expected", [
        (open_(), "OPEN"),
        (closed(), "CLOSED"),
        (open_(is_short=True), "SHORT"),
        (closed(is_short=True), "COVERED"),
        (open_(is_pending=True), "WAITING"),
        (closed(is_pending=True), "WAITING"),
    ])
    def test_status(self, trade, expected):
        assert trade.status == expected

    def test_normalized_instrument(self):
        assert Trade("  aapl ", 1, 1.0).normalized_instrument() == "AAPL"


# ---------- parse_date ----------

class TestParseDate:
    @pytest.mark.parametrize("v", [None, "", "—", "-", "   "])
    def test_empty_values(self, v):
        assert parse_date(v) is None

    @pytest.mark.parametrize("v", ["2024-03-05", "2024/03/05", "03/05/2024"])
    def test_formats(self, v):
        assert parse_date(v) == date(2024, 3, 5)

    def test_dmy_when_unambiguous(self):
        assert parse_date("25/12/2024") == date(2024, 12, 25)

    def test_passthrough_date_and_datetime(self):
        assert parse_date(date(2024, 1, 1)) == date(2024, 1, 1)
        assert parse_date(datetime(2024, 1, 1, 5, 0)) == date(2024, 1, 1)

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_date("not a date")

    def test_date_to_str(self):
        assert pf.date_to_str(date(2024, 1, 2)) == "2024-01-02"
        assert pf.date_to_str(None) == ""


# ---------- business days ----------

class TestBusinessDays:
    def test_none_inputs(self):
        assert pf.business_days_between(None, date(2024, 1, 1)) is None
        assert pf.business_days_between(date(2024, 1, 1), None) is None

    def test_end_before_start_is_zero(self):
        assert pf.business_days_between(date(2024, 1, 9), date(2024, 1, 2)) == 0

    def test_weekend_only_range_is_zero(self):
        assert pf.business_days_between(date(2024, 1, 6), date(2024, 1, 7)) == 0

    def test_full_week_without_holidays(self):
        # Mon 2024-02-05 .. Fri 2024-02-09: five sessions
        assert pf.business_days_between(date(2024, 2, 5), date(2024, 2, 9)) == 5

    def test_year_split_is_plausible(self):
        today = date(2024, 6, 14)
        elapsed = pf.business_days_elapsed_in_year(today)
        remaining = pf.business_days_remaining_in_year(today)
        assert 240 <= elapsed + remaining <= 263

    def test_months_and_weeks_remaining_floor_at_one(self):
        assert pf._current_months_remaining(date(2024, 12, 31)) == 1
        assert pf._current_months_remaining(date(2024, 1, 1)) == 12
        assert pf._weeks_remaining(date(2024, 12, 31)) == 1


# ---------- serialization ----------

class TestSerialization:
    def test_roundtrip(self):
        t = closed(sym="msft", notes="n", account=" Acct ", tag=" swing ", is_short=True)
        back = trade_from_dict(trade_to_dict(t))
        assert back.instrument == "MSFT"
        assert back.account == "Acct" and back.tag == "swing"
        assert back.is_short and back.is_closed
        assert back.open_date == t.open_date and back.close_date == t.close_date

    def test_to_dict_shape(self):
        d = trade_to_dict(open_())
        assert set(d) == {"instrument", "share_count", "buy_price", "sell_price",
                          "open_date", "close_date", "notes", "account",
                          "is_pending", "is_short", "tag", "uid"}
        assert d["sell_price"] is None and d["close_date"] == ""

    def test_old_backup_without_tag_defaults_empty(self):
        t = trade_from_dict({"instrument": "x", "share_count": 1, "buy_price": 2})
        assert t.tag == ""

    def test_from_dict_rejects_bad_input(self):
        assert trade_from_dict("nope") is None
        assert trade_from_dict({"instrument": "  "}) is None
        assert trade_from_dict({"instrument": "A", "share_count": "abc"}) is None
        assert trade_from_dict({"instrument": "A", "open_date": "garbage"}) is None

    def test_from_dict_coerces_and_clamps(self):
        t = trade_from_dict({"instrument": "a", "share_count": "5.9", "buy_price": "2",
                             "sell_price": "—"})
        assert t.share_count == 5 and t.buy_price == 2.0 and t.sell_price is None
        assert trade_from_dict({"instrument": "a", "share_count": -3}).share_count == 0

    def test_json_roundtrip_and_zero_qty_dropped(self):
        trades = [open_(), open_(sym="BBB", qty=0)]
        out = trades_from_json(trades_to_json(trades))
        assert [t.instrument for t in out] == ["AAA"]

    def test_trades_from_json_bad_input(self):
        assert trades_from_json("{bad") == []
        assert trades_from_json({"a": 1}) == []
        out = trades_from_json(json.dumps([1, None, {"instrument": "Z", "share_count": 1}]))
        assert out[0].instrument == "Z"

    def test_trades_from_json_accepts_list(self):
        assert len(trades_from_json([trade_to_dict(open_())])) == 1


# ---------- solve_buy_mark_for_target_avg ----------

class TestSolveBuyMark:
    def test_basic(self):
        # 100 @ 10, buy 100 more to reach avg 8 -> buy at 6
        assert solve_buy_mark_for_target_avg(100, 10.0, 100, 8.0) == pytest.approx(6.0)

    def test_can_return_negative_when_target_unreachable(self):
        assert solve_buy_mark_for_target_avg(100, 10.0, 1, 1.0) < 0

    @pytest.mark.parametrize("args", [(0, 10, 1, 5), (1, 10, 0, 5), (1, 10, 1, 0), (1, 10, 1, -2)])
    def test_validation(self, args):
        with pytest.raises(ValueError):
            solve_buy_mark_for_target_avg(*args)


# ---------- rows / holdings / realized ----------

class TestRowsAndHoldings:
    def test_trade_rows(self):
        rows = compute_trade_rows([open_(), closed(tag=" t ")])
        assert [r.index for r in rows] == [0, 1]
        assert rows[0].status == "OPEN" and rows[0].trade_profit is None
        assert rows[1].trade_profit == pytest.approx(20.0)
        assert rows[1].tag == "t"
        days = pf.business_days_between(date(2024, 1, 2), date(2024, 1, 9))
        assert rows[1].days_to_close == days
        assert rows[1].avg_daily_return == pytest.approx(20.0 / days)

    def test_trade_rows_same_day_close(self):
        d = date(2024, 1, 3)  # a Wednesday: one trading day
        rows = compute_trade_rows([closed(o=d, c=d)])
        assert rows[0].days_to_close == 1 and rows[0].avg_daily_return == pytest.approx(20.0)

    def test_holdings_weighted_average(self):
        h = compute_holdings_from_trades([open_(qty=10, buy=10), open_(qty=30, buy=20)])
        assert len(h) == 1
        assert h[0].qty == 40 and h[0].avg_cost == pytest.approx(17.5)

    def test_holdings_skip_closed_pending_empty(self):
        h = compute_holdings_from_trades([
            closed(), open_(is_pending=True), open_(qty=0), open_(sym="  "),
        ])
        assert h == []

    def test_holdings_shorts_negative_and_sorted_first(self):
        h = compute_holdings_from_trades([
            open_(sym="ZZZ", is_short=True, qty=5), open_(sym="BBB"), open_(sym="AAA"),
        ])
        assert [(x.instrument, x.qty) for x in h] == [("ZZZ", -5), ("AAA", 10), ("BBB", 10)]

    def test_long_and_short_same_symbol_kept_separate(self):
        h = compute_holdings_from_trades([open_(), open_(is_short=True, qty=3)])
        assert sorted(x.qty for x in h) == [-3, 10]

    def test_holdings_notes_joined(self):
        h = compute_holdings_from_trades([open_(notes="a"), open_(notes=""), open_(notes="b")])
        assert h[0].notes == "a | b"

    def test_realized_by_symbol(self):
        out = compute_realized_pl_by_symbol([
            closed(), closed(buy=10, sell=9, qty=10), closed(sym="BBB"),
            open_(), closed(is_pending=True),
        ])
        assert out == {"AAA": pytest.approx(10.0), "BBB": pytest.approx(20.0)}


# ---------- compute_portfolio ----------

class TestComputePortfolio:
    def test_marks_and_weights(self):
        hs = [Holding("aaa", 10, 10.0), Holding("BBB", 10, 20.0)]
        rows, s = compute_portfolio(hs, {"AAA": 12.0, "BBB": 20.0}, {"AAA": 5.0})
        assert rows[0].instrument == "AAA"
        assert rows[0].market_value == pytest.approx(120.0)
        assert rows[0].unrealized_pl == pytest.approx(20.0)
        assert rows[0].total_pl == pytest.approx(25.0)
        assert rows[0].weight_pct == pytest.approx(120 / 320 * 100)
        assert s.market_value == pytest.approx(320.0)
        assert s.cost_basis == pytest.approx(300.0)
        assert s.unrealized_pl == pytest.approx(20.0)
        assert s.realized_pl == pytest.approx(5.0)
        assert s.total_pl == pytest.approx(25.0)
        assert s.positions == 2
        assert s.return_pct == pytest.approx(20 / 300 * 100)

    def test_missing_mark_is_zero_value(self):
        rows, s = compute_portfolio([Holding("AAA", 10, 10.0)], {})
        assert rows[0].mark is None and rows[0].market_value == 0.0
        assert rows[0].unrealized_pl == 0.0 and s.cost_basis == pytest.approx(100.0)

    def test_short_holding(self):
        rows, s = compute_portfolio([Holding("AAA", -10, 10.0)], {"AAA": 8.0})
        assert rows[0].market_value == pytest.approx(-80.0)
        assert rows[0].unrealized_pl == pytest.approx(20.0)  # shorted at 10, now 8
        assert s.return_pct == pytest.approx(20.0)

    def test_empty(self):
        rows, s = compute_portfolio([], {})
        assert rows == [] and s.positions == 0 and s.return_pct is None

    def test_zero_qty_and_blank_filtered(self):
        rows, _ = compute_portfolio([Holding("A", 0, 1.0), Holding(" ", 1, 1.0)], {})
        assert rows == []


# ---------- analytics ----------

class TestAnalytics:
    def test_empty(self):
        a = compute_trade_analytics([])
        assert a.closed_trades == 0 and a.realized_profit == 0.0
        for f in ("avg_profit_per_trade", "win_rate_pct", "max_drawdown",
                  "current_drawdown", "est_yearly_profit", "profit_factor",
                  "avg_daily_closed_profit", "total_roi_pct"):
            assert getattr(a, f) is None, f

    def test_basic_stats(self):
        a = compute_trade_analytics([
            closed(buy=10, sell=12, qty=10),  # +20
            closed(buy=10, sell=9, qty=10),   # -10
            open_(),
        ])
        assert a.closed_trades == 2 and a.open_trades == 1
        assert a.realized_profit == pytest.approx(10.0)
        assert a.avg_profit_per_trade == pytest.approx(5.0)
        assert a.avg_trade_value == pytest.approx(100.0)
        assert a.avg_roi_pct == pytest.approx(5.0)
        assert a.total_roi_pct == pytest.approx(5.0)
        assert a.win_rate_pct == pytest.approx(50.0)
        assert a.avg_win == pytest.approx(20.0) and a.avg_loss == pytest.approx(-10.0)
        assert a.best_trade == pytest.approx(20.0) and a.worst_trade == pytest.approx(-10.0)
        assert a.profit_factor == pytest.approx(2.0)

    def test_profit_factor_none_without_losses_or_wins(self):
        assert compute_trade_analytics([closed()]).profit_factor is None
        assert compute_trade_analytics([closed(sell=9)]).profit_factor is None

    def test_pending_not_counted_closed(self):
        assert compute_trade_analytics([closed(is_pending=True)]).closed_trades == 0

    def test_est_yearly_uses_252(self):
        a = compute_trade_analytics([closed()])
        assert a.est_yearly_profit == pytest.approx(a.avg_daily_closed_profit * 252.0)


class TestDrawdown:
    def _t(self, profit, day):
        return Trade("A", 1, 100.0, 100.0 + profit, date(2024, 1, 1), day)

    def test_drawdown_walk(self):
        d = date(2024, 2, 1)
        trades = [self._t(10, d), self._t(-5, d + timedelta(1)),
                  self._t(-10, d + timedelta(2))]
        a = compute_trade_analytics(trades)
        assert a.max_drawdown == pytest.approx(15.0)
        assert a.current_drawdown == pytest.approx(15.0)
        a = compute_trade_analytics(trades + [self._t(20, d + timedelta(3))])
        assert a.max_drawdown == pytest.approx(15.0)
        assert a.current_drawdown == pytest.approx(0.0)

    def test_sorted_by_close_date_not_storage_order(self):
        d = date(2024, 2, 1)
        shuffled = [self._t(-10, d + timedelta(2)), self._t(10, d), self._t(-5, d + timedelta(1))]
        assert compute_trade_analytics(shuffled).max_drawdown == pytest.approx(15.0)

    def test_losing_first_trade_counts_from_zero_peak(self):
        a = compute_trade_analytics([self._t(-7, date(2024, 2, 1))])
        assert a.max_drawdown == pytest.approx(7.0)
        assert a.current_drawdown == pytest.approx(7.0)

    def test_all_wins_zero_drawdown(self):
        d = date(2024, 2, 1)
        a = compute_trade_analytics([self._t(5, d), self._t(5, d + timedelta(1))])
        assert a.max_drawdown == 0.0 and a.current_drawdown == 0.0


# ---------- goal progress ----------

class TestGoalProgress:
    def test_numbers(self):
        today = date(2024, 6, 14)
        g = compute_goal_progress([closed(), open_()], 1000.0, unrealized_profit=5.0, today=today)
        assert g.realized_profit == pytest.approx(20.0)
        assert g.total_profit == pytest.approx(25.0)
        assert g.remaining_profit == pytest.approx(980.0)
        assert g.monthly_profit_to_goal == pytest.approx(980.0 / 7)
        assert g.weekly_profit_to_goal == pytest.approx(980.0 / pf._weeks_remaining(today))
        assert g.daily_profit_to_goal == pytest.approx(980.0 / g.business_days_remaining)
        assert g.avg_daily_profit == pytest.approx(20.0 / g.business_days_elapsed)
        total = g.business_days_elapsed + g.business_days_remaining
        expected = 1000.0 * g.business_days_elapsed / total
        assert g.profit_to_match_daily_avg == pytest.approx(max(0.0, expected - 20.0))

    def test_goal_exceeded_clamps_match_to_zero(self):
        g = compute_goal_progress([closed()], 10.0, today=date(2024, 6, 14))
        assert g.remaining_profit < 0 and g.profit_to_match_daily_avg == 0.0

    def test_pending_excluded(self):
        g = compute_goal_progress([closed(is_pending=True)], 100.0, today=date(2024, 6, 14))
        assert g.realized_profit == 0.0

    def test_last_day_of_year_no_division_error(self):
        g = compute_goal_progress([], 100.0, today=date(2024, 12, 31))
        assert g.monthly_profit_to_goal == pytest.approx(100.0)


# ---------- date-range filter ----------

class TestDateRangeFilter:
    TODAY = date(2024, 5, 15)  # Wednesday

    def _trades(self):
        return [
            closed(c=date(2024, 5, 14), o=date(2024, 5, 1)),   # 0 this week (Tue)
            closed(c=date(2024, 5, 10), o=date(2024, 5, 1)),   # 1 this month, not week
            closed(c=date(2024, 4, 20), o=date(2024, 4, 1)),   # 2 within 30d, not month
            closed(c=date(2024, 2, 1), o=date(2024, 1, 5)),    # 3 ytd only
            closed(c=date(2023, 12, 1), o=date(2023, 11, 1)),  # 4 last year
            open_(o=date(2024, 5, 15)),                        # 5 open today
            open_(o=date(2020, 1, 1), is_pending=True),        # 6 pending, old
            Trade("N", 1, 1.0),                                # 7 no dates
        ]

    def _idx(self, key):
        out = filter_trades_by_date_range_with_orig_index(self._trades(), key, self.TODAY)
        return [i for i, _ in out]

    def test_all_and_unknown(self):
        assert self._idx("all") == list(range(8))
        assert self._idx("bogus") == list(range(8))

    def test_week(self):
        assert self._idx("week") == [0, 5, 6, 7]

    def test_month(self):
        assert self._idx("month") == [0, 1, 5, 6, 7]

    def test_30d(self):
        # 2024-05-15 - 30d = 2024-04-15
        assert self._idx("30d") == [0, 1, 2, 5, 6, 7]

    def test_ytd(self):
        assert self._idx("ytd") == [0, 1, 2, 3, 5, 6, 7]

    def test_original_indices_preserved_and_objects_identical(self):
        trades = self._trades()
        out = filter_trades_by_date_range_with_orig_index(trades, "week", self.TODAY)
        for i, t in out:
            assert trades[i] is t
        assert [i for i, _ in out] != list(range(len(out)))

    def test_boundary_start_day_inclusive(self):
        t = [closed(c=date(2024, 4, 15))]
        assert len(filter_trades_by_date_range_with_orig_index(t, "30d", self.TODAY)) == 1
        t = [closed(c=date(2024, 4, 14))]
        assert filter_trades_by_date_range_with_orig_index(t, "30d", self.TODAY) == []

    def test_open_trade_uses_open_date(self):
        t = [open_(o=date(2024, 5, 1))]
        assert filter_trades_by_date_range_with_orig_index(t, "week", self.TODAY) == []

    def test_all_returns_pairs(self):
        trades = [open_()]
        assert filter_trades_by_date_range_with_orig_index(trades, "all") == [(0, trades[0])]

    def test_empty(self):
        assert filter_trades_by_date_range_with_orig_index([], "week", self.TODAY) == []


# ---------- tags ----------

class TestTags:
    def test_tag_default_empty_and_stripped(self):
        assert Trade("A", 1, 1.0).tag == ""
        assert trade_to_dict(Trade("A", 1, 1.0, tag="  earnings "))["tag"] == "earnings"

    def test_tag_none_safe(self):
        t = Trade("A", 1, 1.0)
        t.tag = None
        assert trade_to_dict(t)["tag"] == ""
        assert compute_trade_rows([t])[0].tag == ""

    def test_tag_survives_json(self):
        out = trades_from_json(trades_to_json([open_(tag="swing")]))
        assert out[0].tag == "swing"

    def test_tag_null_in_dict(self):
        assert trade_from_dict({"instrument": "A", "tag": None}).tag == ""


# ---------- uid (trade identity) ----------

class TestUid:
    def test_generated_on_construction(self):
        a, b = Trade("A", 1, 1.0), Trade("A", 1, 1.0)
        assert pf._UID_RE.fullmatch(a.uid) and pf._UID_RE.fullmatch(b.uid)
        assert a.uid != b.uid

    def test_not_part_of_equality(self):
        assert Trade("A", 1, 1.0) == Trade("A", 1, 1.0)
        assert Trade("A", 1, 1.0) != Trade("A", 2, 1.0)

    def test_given_uid_kept_and_normalised(self):
        uid = "0123456789abcdef0123456789abcdef"
        assert Trade("A", 1, 1.0, uid=uid).uid == uid
        dashed = "01234567-89AB-CDEF-0123-456789ABCDEF"
        assert Trade("A", 1, 1.0, uid=dashed).uid == uid

    @pytest.mark.parametrize("bad", ["", None, "xyz", "123", "g" * 32])
    def test_bad_uid_replaced(self, bad):
        assert pf._UID_RE.fullmatch(Trade("A", 1, 1.0, uid=bad).uid)

    def test_roundtrips_through_dict_and_json(self):
        t = open_(tag="swing")
        assert trade_to_dict(t)["uid"] == t.uid
        assert trade_from_dict(trade_to_dict(t)).uid == t.uid
        assert trades_from_json(trades_to_json([t]))[0].uid == t.uid

    def test_missing_uid_generated_on_load(self):
        rows = [{"instrument": "A", "share_count": 1, "buy_price": 1},
                {"instrument": "B", "share_count": 1, "buy_price": 1, "uid": None}]
        out = trades_from_json(rows)
        assert all(pf._UID_RE.fullmatch(t.uid) for t in out)
        assert out[0].uid != out[1].uid

    def test_duplicate_uid_in_file_made_unique(self):
        uid = "a" * 32
        rows = [{"instrument": "A", "share_count": 1, "buy_price": 1, "uid": uid},
                {"instrument": "B", "share_count": 1, "buy_price": 1, "uid": uid}]
        out = trades_from_json(rows)
        assert out[0].uid == uid and out[1].uid != uid

    def test_replace_keeps_uid(self):
        from dataclasses import replace
        t = open_()
        assert replace(t, account="Other").uid == t.uid
