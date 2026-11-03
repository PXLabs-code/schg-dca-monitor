"""技术指标单元测试：RSI(Wilder)、SMA、252 日最高、回撤、偏离率、月末比较。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from tests.conftest import make_series

from schg_monitor import indicators as ind


class TestRollingMaxAndDrawdown:
    def test_rolling_max_uses_window(self):
        prices = [100.0] * 251 + [200.0] + [150.0] * 252
        s = make_series(prices)
        rm = ind.rolling_max_close(s, 252)
        assert rm.iloc[251] == 200.0
        # 200 落出 252 日窗口后，最高价应回落为 150
        assert rm.iloc[-1] == 150.0

    def test_drawdown_exact_20_percent(self):
        """边界：回撤恰好 20%。"""
        prices = [100.0] * 252 + [80.0]
        s = make_series(prices)
        dd = ind.drawdown_pct(s, 252).iloc[-1]
        assert dd == pytest.approx(0.20)

    def test_drawdown_below_threshold(self):
        prices = [100.0] * 252 + [81.0]
        s = make_series(prices)
        assert ind.drawdown_pct(s, 252).iloc[-1] < 0.20

    def test_insufficient_history_is_nan(self):
        s = make_series([100.0] * 100)
        assert math.isnan(ind.rolling_max_close(s, 252).iloc[-1])

    def test_no_lookahead(self):
        """指标值只能依赖当前及过去数据。"""
        prices = [100.0] * 252 + [50.0, 500.0]
        s = make_series(prices)
        rm = ind.rolling_max_close(s, 252)
        assert rm.iloc[-2] == 100.0  # 不应看到后一天的 500


class TestRSIWilder:
    def test_all_gains_is_100(self):
        s = make_series([float(i) for i in range(1, 60)])
        assert ind.rsi_wilder(s, 14).iloc[-1] == pytest.approx(100.0)

    def test_all_losses_near_0(self):
        s = make_series([float(i) for i in range(200, 100, -1)])
        assert ind.rsi_wilder(s, 14).iloc[-1] < 5.0

    def test_wilder_textbook_value(self):
        """对照 Wilder 原著示例数据验证平滑算法。"""
        closes = [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45,
            45.78, 45.35, 44.03, 44.18, 44.22, 44.57, 43.42, 42.66, 43.13,
        ]
        s = make_series(closes)
        rsi = ind.rsi_wilder(s, 14)
        # 公认参考值（Wilder 平滑）：第 14 期约 70.46，末期约 37.79
        assert rsi.iloc[14] == pytest.approx(70.46, abs=0.1)
        assert rsi.iloc[-1] == pytest.approx(37.79, abs=0.2)

    def test_insufficient_data_is_nan(self):
        s = make_series([100.0, 101.0, 102.0])
        assert ind.rsi_wilder(s, 14).isna().all()

    def test_flat_prices(self):
        """无涨无跌：avg_loss=0，约定 RSI=100（不产生 NaN/除零）。"""
        s = make_series([100.0] * 40)
        val = ind.rsi_wilder(s, 14).iloc[-1]
        assert not math.isnan(val)


class TestSMA:
    def test_sma_value(self):
        s = make_series([float(i) for i in range(1, 301)])
        expected = np.mean(range(101, 301))
        assert ind.sma(s, 200).iloc[-1] == pytest.approx(expected)

    def test_deviation_exact_15_percent(self):
        """边界：偏离率恰好 +15%。"""
        s = make_series([100.0] * 200)
        s.iloc[-1] = 100.0  # SMA 受最后一个值影响，需构造
        # 构造：前 199 日价格 p，最后一日 x，使 x = 1.15 * sma
        p = 100.0
        # sma = (199p + x)/200; x = 1.15*sma => x = 1.15*(199p + x)/200
        x = 1.15 * 199 * p / (200 - 1.15)
        prices = [p] * 199 + [x]
        s2 = make_series(prices)
        dev = ind.sma_deviation(s2, 200).iloc[-1]
        assert dev == pytest.approx(0.15)

    def test_insufficient_window_nan(self):
        s = make_series([100.0] * 150)
        assert math.isnan(ind.sma(s, 200).iloc[-1])


class TestMonthEnd:
    def test_month_end_skips_holidays(self):
        """月末最后一天若为节假日（无数据），应取最后一个有效交易日。"""
        idx = pd.bdate_range("2023-11-01", "2023-12-29")
        # 模拟 2023-11-23 感恩节休市 + 12-25 圣诞休市
        idx = idx[~idx.isin([pd.Timestamp("2023-11-23"), pd.Timestamp("2023-12-25")])]
        s = pd.Series(range(len(idx)), index=idx, dtype=float)
        me = ind.month_end_closes(s)
        assert pd.Timestamp("2023-11-30") in me.index
        assert pd.Timestamp("2023-12-29") in me.index
        assert len(me) == 2

    def test_month_end_last_day_is_holiday(self):
        """若月末最后一个工作日休市，取前一个交易日。"""
        idx = pd.bdate_range("2024-03-01", "2024-03-29")
        # 2024-03-29 是耶稣受难日，美股休市
        idx = idx[idx != pd.Timestamp("2024-03-29")]
        s = pd.Series(range(len(idx)), index=idx, dtype=float)
        me = ind.month_end_closes(s)
        assert me.index[-1] == pd.Timestamp("2024-03-28")

    def test_monthly_up(self):
        idx = pd.bdate_range("2024-01-01", "2024-03-29")
        s = pd.Series(100.0, index=idx)
        s.loc["2024-02-29"] = 110.0
        s.loc["2024-03-28":"2024-03-29"] = 105.0
        up = ind.monthly_close_up(s)
        assert bool(up.iloc[1]) is True   # 2月末 110 > 1月末 100
        assert bool(up.iloc[2]) is False  # 3月末 105 < 2月末 110

    def test_missing_data_dropped(self):
        idx = pd.bdate_range("2024-01-01", periods=30)
        s = pd.Series(100.0, index=idx)
        s.iloc[5] = float("nan")
        me = ind.month_end_closes(s)
        assert not me.isna().any()
