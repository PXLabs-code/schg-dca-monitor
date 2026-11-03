"""状态与信号持久化（JSON 文件）。

- state.json：当前策略状态机状态。
- signals.json：历史信号记录；同月同信号不得重复记录（幂等）。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .strategy import Decision, State, StrategyState


class StateStore:
    def __init__(self, state_file: Path, signals_file: Path) -> None:
        self.state_file = state_file
        self.signals_file = signals_file

    # ---------- 状态 ----------
    def load_state(self) -> StrategyState:
        if not self.state_file.exists():
            return StrategyState()
        data = json.loads(self.state_file.read_text())
        return StrategyState(
            state=State(data.get("state", "NORMAL")),
            months_in_state=int(data.get("months_in_state", 0)),
            last_signal_month=data.get("last_signal_month"),
        )

    def save_state(self, state: StrategyState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": state.state.value,
            "months_in_state": state.months_in_state,
            "last_signal_month": state.last_signal_month,
        }
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # ---------- 信号 ----------
    def load_signals(self) -> list[dict]:
        if not self.signals_file.exists():
            return []
        return json.loads(self.signals_file.read_text())

    def has_signal_for_month(self, month: str) -> bool:
        """同月是否已记录信号（防止重复触发/重复通知/定时任务重复运行）。"""
        return any(s.get("month") == month for s in self.load_signals())

    def record_signal(self, decision: Decision, notified: bool, extra: dict | None = None) -> bool:
        """记录信号；若同月已存在则拒绝写入并返回 False。"""
        signals = self.load_signals()
        if any(s.get("month") == decision.month for s in signals):
            return False
        entry = asdict(decision)
        entry["state"] = decision.state.value
        entry["notified"] = notified
        if extra:
            entry.update(extra)
        signals.append(entry)
        self.signals_file.parent.mkdir(parents=True, exist_ok=True)
        self.signals_file.write_text(json.dumps(signals, ensure_ascii=False, indent=2))
        return True

    def mark_notified(self, month: str) -> None:
        signals = self.load_signals()
        for s in signals:
            if s.get("month") == month:
                s["notified"] = True
        self.signals_file.write_text(json.dumps(signals, ensure_ascii=False, indent=2))
