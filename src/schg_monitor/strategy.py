"""策略引擎：明确的三状态状态机（NORMAL / DOUBLE / HALF）。

决策规则（均基于月末最后一个有效交易日的数据）：
- 减半（HALF）：RSI(14) >= rsi_overbought 且 偏离 SMA200 >= sma_deviation_threshold
- 加倍（DOUBLE）：252 日回撤 >= drawdown_threshold 且 当月末收盘 > 上月末收盘；
  最多连续 3 个月，之后强制恢复正常
- 减半恢复：RSI(14) < rsi_recovery 且 偏离 <= sma_deviation_recovery，
  满足一个月后恢复正常
- 优先级：减半 > 加倍
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from . import indicators as ind
from .config import StrategyConfig


class State(StrEnum):
    NORMAL = "NORMAL"
    DOUBLE = "DOUBLE"
    HALF = "HALF"


@dataclass
class StrategyState:
    """持久化的策略状态。"""

    state: State = State.NORMAL
    months_in_state: int = 0           # 当前状态已持续月数（含本月）
    last_signal_month: str | None = None  # "YYYY-MM"，防止同月重复触发


@dataclass
class Decision:
    """策略引擎输出。"""

    month: str                      # 决策月份 "YYYY-MM"
    decision_date: str              # 月末最后交易日 "YYYY-MM-DD"
    state: State
    amount: float
    close: float
    rsi14: float
    sma200: float
    high_252: float
    drawdown: float                 # 回撤比例（正数）
    sma_dev: float                  # 均线偏离率（可正可负）
    monthly_up: bool                # 当月末收盘是否高于上月末
    months_in_state: int
    reasons: list[str] = field(default_factory=list)
    next_check_date: str = ""


class StrategyEngine:
    def __init__(self, config: StrategyConfig) -> None:
        self.cfg = config

    # ---------- 指标快照 ----------
    def compute_snapshot(self, close: pd.Series, as_of: pd.Timestamp) -> dict:
        """计算截至 as_of（含）的指标，严禁使用 as_of 之后的数据。"""
        hist = close.loc[:as_of]
        if len(hist) < self.cfg.min_history_days:
            raise ValueError(
                f"历史数据不足：需要 {self.cfg.min_history_days}，实际 {len(hist)}"
            )
        rsi = ind.rsi_wilder(hist, self.cfg.rsi_period).iloc[-1]
        sma200 = ind.sma(hist, self.cfg.sma_window).iloc[-1]
        high = ind.rolling_max_close(hist, self.cfg.lookback_high_window).iloc[-1]
        dd = ind.drawdown_pct(hist, self.cfg.lookback_high_window).iloc[-1]
        dev = ind.sma_deviation(hist, self.cfg.sma_window).iloc[-1]
        me = ind.month_end_closes(hist)
        monthly_up = bool(len(me) >= 2 and me.iloc[-1] > me.iloc[-2])
        snapshot = {
            "close": float(hist.iloc[-1]),
            "rsi14": float(rsi),
            "sma200": float(sma200),
            "high_252": float(high),
            "drawdown": float(dd),
            "sma_dev": float(dev),
            "monthly_up": monthly_up,
            "date": hist.index[-1],
        }
        for key in ("rsi14", "sma200", "high_252", "drawdown", "sma_dev"):
            if math.isnan(snapshot[key]):
                raise ValueError(f"指标 {key} 为 NaN（历史窗口不足），禁止生成信号")
        return snapshot

    # ---------- 状态机 ----------
    def decide(self, close: pd.Series, state: StrategyState, as_of: pd.Timestamp | None = None) -> Decision:
        """基于月末数据做出一次月度决策，并返回新状态下的 Decision。

        注意：本方法是纯函数式决策（不修改传入 state）；调用方应据返回值更新状态。
        """
        cfg = self.cfg
        if as_of is None:
            as_of = close.index[-1]
        snap = self.compute_snapshot(close, as_of)
        decision_date: pd.Timestamp = snap["date"]
        month = decision_date.strftime("%Y-%m")

        half_cond = (
            snap["rsi14"] >= cfg.rsi_overbought
            and snap["sma_dev"] >= cfg.sma_deviation_threshold
        )
        double_cond = (
            snap["drawdown"] >= cfg.drawdown_threshold and snap["monthly_up"]
        )
        recovery_cond = (
            snap["rsi14"] < cfg.rsi_recovery
            and snap["sma_dev"] <= cfg.sma_deviation_recovery
        )

        reasons: list[str] = []
        prev_state = state.state

        # 优先级：减半 > 加倍
        if half_cond:
            new_state = State.HALF
            reasons.append(
                f"减半触发：RSI(14)={snap['rsi14']:.1f} >= {cfg.rsi_overbought}"
                f" 且 偏离 SMA200 {snap['sma_dev']:+.1%} >= {cfg.sma_deviation_threshold:.0%}"
            )
            if double_cond:
                reasons.append("加倍条件同时满足，但减半优先级更高")
        elif prev_state == State.HALF:
            if recovery_cond:
                new_state = State.NORMAL
                reasons.append(
                    f"减半恢复：RSI(14)={snap['rsi14']:.1f} < {cfg.rsi_recovery}"
                    f" 且 偏离 {snap['sma_dev']:+.1%} <= {cfg.sma_deviation_recovery:.0%}"
                )
            else:
                new_state = State.HALF
                reasons.append("维持减半：恢复条件未满足")
        elif double_cond:
            if prev_state == State.DOUBLE and state.months_in_state >= cfg.double_max_months:
                new_state = State.NORMAL
                reasons.append(
                    f"加倍已持续 {state.months_in_state} 个月（上限 {cfg.double_max_months}），强制恢复正常"
                )
            else:
                new_state = State.DOUBLE
                reasons.append(
                    f"加倍触发：252 日回撤 {snap['drawdown']:.1%} >= {cfg.drawdown_threshold:.0%}"
                    " 且 当月末收盘高于上月末"
                )
        else:
            new_state = State.NORMAL
            if prev_state == State.DOUBLE:
                reasons.append("加倍条件不再满足，恢复正常定投")
            else:
                reasons.append("正常定投：未触发加倍或减半条件")

        months_in_state = state.months_in_state + 1 if new_state == prev_state else 1
        amount = {
            State.NORMAL: cfg.base_amount,
            State.DOUBLE: cfg.double_amount,
            State.HALF: cfg.half_amount,
        }[new_state]

        next_check = (decision_date + pd.offsets.BMonthEnd(1)).strftime("%Y-%m-%d")
        return Decision(
            month=month,
            decision_date=decision_date.strftime("%Y-%m-%d"),
            state=new_state,
            amount=amount,
            close=snap["close"],
            rsi14=snap["rsi14"],
            sma200=snap["sma200"],
            high_252=snap["high_252"],
            drawdown=snap["drawdown"],
            sma_dev=snap["sma_dev"],
            monthly_up=snap["monthly_up"],
            months_in_state=months_in_state,
            reasons=reasons,
            next_check_date=next_check,
        )

    @staticmethod
    def apply(state: StrategyState, decision: Decision) -> StrategyState:
        """根据决策生成新的持久化状态。"""
        return StrategyState(
            state=decision.state,
            months_in_state=decision.months_in_state,
            last_signal_month=decision.month,
        )
