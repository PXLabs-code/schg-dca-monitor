"""回测模块测试：无未来数据、执行时点滞后、统计正确性。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from schg_monitor.backtest import run_backtest
from schg_monitor.config import StrategyConfig


def make_long_series(n_days=800, seed=7) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n_days)
    rets = rng.normal(0.0004, 0.012, n_days)
    prices = 100.0 * np.exp(np.cumsum(rets))
    return pd.Series(prices, index=idx, name="close")


class TestBacktest:
    def test_runs_and_counts(self):
        s = make_long_series()
        cfg = StrategyConfig()
        res = run_backtest(s, cfg)
        assert len(res.records) > 0
        assert res.months_double + res.months_half + res.months_normal == len(res.records)

    def test_execution_after_signal(self):
        """执行日必须晚于信号日（信号生成与执行时间分离）。"""
        s = make_long_series()
        res = run_backtest(s, StrategyConfig())
        for r in res.records:
            if r["exec_date"] is not None:
                assert r["exec_date"] > r["signal_date"]

    def test_fixed_comparison(self):
        s = make_long_series()
        res = run_backtest(s, StrategyConfig())
        executed = [r for r in res.records if r["exec_price"] is not None]
        assert res.fixed_total_invested == 2000.0 * len(executed)
        assert res.total_invested == sum(r["amount"] for r in executed)

    def test_no_signal_before_min_history(self):
        s = make_long_series()
        cfg = StrategyConfig()
        res = run_backtest(s, cfg)
        first_signal = pd.Timestamp(res.records[0]["signal_date"])
        assert len(s.loc[:first_signal]) >= cfg.min_history_days

    def test_summary_contains_stats(self):
        res = run_backtest(make_long_series(), StrategyConfig())
        text = res.summary()
        assert "加倍次数" in text
        assert "累计投入" in text
        assert "固定定投" in text

    def test_deterministic(self):
        s = make_long_series()
        r1 = run_backtest(s, StrategyConfig())
        r2 = run_backtest(s, StrategyConfig())
        assert r1.records == r2.records
