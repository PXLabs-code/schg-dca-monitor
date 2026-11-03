"""状态持久化与幂等测试：同月重复执行、重启后不重复通知、定时任务重复运行。"""

from __future__ import annotations

from schg_monitor.state_store import StateStore
from schg_monitor.strategy import Decision, State, StrategyState


def make_decision(month="2024-06") -> Decision:
    return Decision(
        month=month, decision_date=f"{month}-28", state=State.NORMAL, amount=2000.0,
        close=100.0, rsi14=50.0, sma200=95.0, high_252=110.0, drawdown=0.09,
        sma_dev=0.05, monthly_up=True, months_in_state=1,
        reasons=["正常"], next_check_date="2024-07-31",
    )


class TestStatePersistence:
    def test_roundtrip(self, tmp_path):
        store = StateStore(tmp_path / "state.json", tmp_path / "signals.json")
        s = StrategyState(state=State.HALF, months_in_state=2, last_signal_month="2024-06")
        store.save_state(s)
        loaded = store.load_state()
        assert loaded == s

    def test_default_state_when_missing(self, tmp_path):
        store = StateStore(tmp_path / "state.json", tmp_path / "signals.json")
        assert store.load_state() == StrategyState()


class TestSignalDedup:
    def test_same_month_recorded_once(self, tmp_path):
        """同月同信号不得重复记录（launchd 重复运行场景）。"""
        store = StateStore(tmp_path / "state.json", tmp_path / "signals.json")
        d = make_decision()
        assert store.record_signal(d, notified=True) is True
        assert store.record_signal(d, notified=True) is False
        assert len(store.load_signals()) == 1

    def test_has_signal_for_month(self, tmp_path):
        store = StateStore(tmp_path / "state.json", tmp_path / "signals.json")
        store.record_signal(make_decision("2024-06"), notified=True)
        assert store.has_signal_for_month("2024-06") is True
        assert store.has_signal_for_month("2024-07") is False

    def test_restart_does_not_resend(self, tmp_path):
        """模拟程序重启：新建 StateStore 实例读取同一文件，仍能识别已发月份。"""
        f1, f2 = tmp_path / "state.json", tmp_path / "signals.json"
        StateStore(f1, f2).record_signal(make_decision("2024-06"), notified=True)
        fresh = StateStore(f1, f2)  # 重启
        assert fresh.has_signal_for_month("2024-06") is True

    def test_different_months_recorded(self, tmp_path):
        store = StateStore(tmp_path / "state.json", tmp_path / "signals.json")
        store.record_signal(make_decision("2024-06"), notified=True)
        store.record_signal(make_decision("2024-07"), notified=False)
        signals = store.load_signals()
        assert len(signals) == 2
        assert signals[1]["notified"] is False

    def test_mark_notified(self, tmp_path):
        store = StateStore(tmp_path / "state.json", tmp_path / "signals.json")
        store.record_signal(make_decision("2024-06"), notified=False)
        store.mark_notified("2024-06")
        assert store.load_signals()[0]["notified"] is True
