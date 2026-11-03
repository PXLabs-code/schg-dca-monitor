"""策略引擎与状态机测试。

通过注入指标快照（monkeypatch compute_snapshot）精确测试状态机逻辑与边界值；
另有基于合成行情的端到端测试。
"""

from __future__ import annotations

import pandas as pd
import pytest
from tests.conftest import make_series

from schg_monitor.config import StrategyConfig
from schg_monitor.strategy import State, StrategyEngine, StrategyState

CFG = StrategyConfig()


def snap(
    close=100.0, rsi14=50.0, sma200=100.0, high_252=100.0,
    drawdown=0.0, sma_dev=0.0, monthly_up=False, date="2024-06-28",
) -> dict:
    return {
        "close": close, "rsi14": rsi14, "sma200": sma200, "high_252": high_252,
        "drawdown": drawdown, "sma_dev": sma_dev, "monthly_up": monthly_up,
        "date": pd.Timestamp(date),
    }


@pytest.fixture
def engine() -> StrategyEngine:
    return StrategyEngine(CFG)


def decide_with(engine, monkeypatch, snapshot, state=None):
    monkeypatch.setattr(engine, "compute_snapshot", lambda *_: snapshot)
    dummy = make_series([100.0] * 2)
    return engine.decide(dummy, state or StrategyState())


class TestDoubleTrigger:
    def test_drawdown_exact_20_and_monthly_up_triggers_double(self, engine, monkeypatch):
        """边界：回撤恰好 20% 应触发加倍。"""
        d = decide_with(engine, monkeypatch, snap(drawdown=0.20, monthly_up=True))
        assert d.state == State.DOUBLE
        assert d.amount == 4000.0

    def test_drawdown_just_below_20_no_double(self, engine, monkeypatch):
        d = decide_with(engine, monkeypatch, snap(drawdown=0.1999, monthly_up=True))
        assert d.state == State.NORMAL
        assert d.amount == 2000.0

    def test_drawdown_20_but_monthly_down_no_double(self, engine, monkeypatch):
        d = decide_with(engine, monkeypatch, snap(drawdown=0.25, monthly_up=False))
        assert d.state == State.NORMAL

    def test_double_max_3_months_then_normal(self, engine, monkeypatch):
        """加倍最多持续 3 个月，第 4 个月即使条件仍满足也恢复正常。"""
        state = StrategyState()
        s = snap(drawdown=0.30, monthly_up=True)
        states = []
        for _ in range(4):
            d = decide_with(engine, monkeypatch, s, state)
            states.append(d.state)
            state = StrategyEngine.apply(state, d)
        assert states == [State.DOUBLE, State.DOUBLE, State.DOUBLE, State.NORMAL]

    def test_double_can_retrigger_after_reset(self, engine, monkeypatch):
        state = StrategyState(state=State.NORMAL, months_in_state=1)
        d = decide_with(engine, monkeypatch, snap(drawdown=0.30, monthly_up=True), state)
        assert d.state == State.DOUBLE
        assert d.months_in_state == 1


class TestHalfTrigger:
    def test_rsi_exact_75_and_dev_exact_15_triggers_half(self, engine, monkeypatch):
        """边界：RSI 恰好 75 且偏离恰好 15% 应触发减半。"""
        d = decide_with(engine, monkeypatch, snap(rsi14=75.0, sma_dev=0.15))
        assert d.state == State.HALF
        assert d.amount == 1000.0

    def test_rsi_below_75_no_half(self, engine, monkeypatch):
        d = decide_with(engine, monkeypatch, snap(rsi14=74.99, sma_dev=0.20))
        assert d.state == State.NORMAL

    def test_dev_below_15_no_half(self, engine, monkeypatch):
        d = decide_with(engine, monkeypatch, snap(rsi14=80.0, sma_dev=0.1499))
        assert d.state == State.NORMAL

    def test_half_priority_over_double(self, engine, monkeypatch):
        """同时满足加倍与减半 → 执行减半。"""
        d = decide_with(
            engine, monkeypatch,
            snap(rsi14=80.0, sma_dev=0.20, drawdown=0.25, monthly_up=True),
        )
        assert d.state == State.HALF
        assert d.amount == 1000.0
        assert any("优先" in r for r in d.reasons)


class TestHalfRecovery:
    def test_recovery_boundary_rsi_and_dev(self, engine, monkeypatch):
        """边界：RSI=64.99（<65）且偏离恰好 10%（<=10%）→ 恢复正常。"""
        state = StrategyState(state=State.HALF, months_in_state=2)
        d = decide_with(engine, monkeypatch, snap(rsi14=64.99, sma_dev=0.10), state)
        assert d.state == State.NORMAL
        assert d.amount == 2000.0

    def test_rsi_exact_65_no_recovery(self, engine, monkeypatch):
        """边界：RSI 恰好 65 不满足 <65，维持减半。"""
        state = StrategyState(state=State.HALF, months_in_state=1)
        d = decide_with(engine, monkeypatch, snap(rsi14=65.0, sma_dev=0.05), state)
        assert d.state == State.HALF

    def test_dev_above_10_no_recovery(self, engine, monkeypatch):
        state = StrategyState(state=State.HALF, months_in_state=1)
        d = decide_with(engine, monkeypatch, snap(rsi14=50.0, sma_dev=0.101), state)
        assert d.state == State.HALF

    def test_half_persists_while_overbought(self, engine, monkeypatch):
        state = StrategyState(state=State.HALF, months_in_state=1)
        d = decide_with(engine, monkeypatch, snap(rsi14=76.0, sma_dev=0.16), state)
        assert d.state == State.HALF
        assert d.months_in_state == 2


class TestStateTransitions:
    def test_months_in_state_increments(self, engine, monkeypatch):
        state = StrategyState(state=State.NORMAL, months_in_state=5)
        d = decide_with(engine, monkeypatch, snap(), state)
        assert d.months_in_state == 6

    def test_apply_updates_last_signal_month(self, engine, monkeypatch):
        d = decide_with(engine, monkeypatch, snap(date="2024-06-28"))
        new = StrategyEngine.apply(StrategyState(), d)
        assert new.last_signal_month == "2024-06"

    def test_next_check_date_is_next_month_end(self, engine, monkeypatch):
        d = decide_with(engine, monkeypatch, snap(date="2024-06-28"))
        assert d.next_check_date == "2024-07-31"


class TestEndToEnd:
    def test_insufficient_history_raises(self, engine):
        s = make_series([100.0] * 100)
        with pytest.raises(ValueError, match="历史数据不足"):
            engine.decide(s, StrategyState())

    def test_no_lookahead_in_decide(self, engine):
        """as_of 之后的数据不得影响决策。"""
        base = [100.0 + i * 0.01 for i in range(320)]
        s1 = make_series(base)
        s2 = make_series(base + [999.0, 1.0])
        as_of = s1.index[-1]
        d1 = engine.decide(s1, StrategyState(), as_of=as_of)
        d2 = engine.decide(s2, StrategyState(), as_of=as_of)
        assert d1.close == d2.close
        assert d1.rsi14 == d2.rsi14
        assert d1.state == d2.state

    def test_real_series_double(self, engine):
        """合成序列：高点后回撤 25%，最后一个月反弹 → 加倍。"""
        prices = [100.0] * 260
        # 回撤至 72（-28%），随后缓慢反弹到 75（月度上涨）
        prices += [72.0] * 40 + [73.0, 74.0, 75.0] * 10
        s = make_series(prices)
        d = engine.decide(s, StrategyState())
        assert d.drawdown >= 0.20
        if d.monthly_up:
            assert d.state == State.DOUBLE
