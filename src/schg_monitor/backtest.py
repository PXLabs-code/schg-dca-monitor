"""历史行情回测模块。

逐月回放：每个月末最后交易日，仅用截至当日的数据生成信号（无未来数据）；
实际执行发生在【下一个交易日】（信号生成时间 ≠ 执行时间），
买入价采用执行日收盘价。统计各状态持续时间、触发次数、
累计/每月投入金额，并与固定 2000 USD 定投对比。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import StrategyConfig
from .indicators import month_end_closes
from .strategy import State, StrategyEngine, StrategyState


@dataclass
class BacktestResult:
    records: list[dict] = field(default_factory=list)
    months_double: int = 0
    months_half: int = 0
    months_normal: int = 0
    total_invested: float = 0.0
    fixed_total_invested: float = 0.0
    strategy_shares: float = 0.0
    fixed_shares: float = 0.0
    final_price: float = 0.0

    @property
    def strategy_value(self) -> float:
        return self.strategy_shares * self.final_price

    @property
    def fixed_value(self) -> float:
        return self.fixed_shares * self.final_price

    def summary(self) -> str:
        lines = [
            "===== SCHG DCA 回测结果 =====",
            f"回测月数：{len(self.records)}",
            f"加倍次数：{self.months_double}  减半次数：{self.months_half}  正常次数：{self.months_normal}",
            f"策略累计投入：{self.total_invested:,.0f} USD",
            f"固定定投累计投入：{self.fixed_total_invested:,.0f} USD",
            f"策略期末市值：{self.strategy_value:,.0f} USD（收益率 "
            f"{(self.strategy_value / self.total_invested - 1) if self.total_invested else 0:.2%}）",
            f"固定定投期末市值：{self.fixed_value:,.0f} USD（收益率 "
            f"{(self.fixed_value / self.fixed_total_invested - 1) if self.fixed_total_invested else 0:.2%}）",
        ]
        return "\n".join(lines)


def run_backtest(
    close: pd.Series, config: StrategyConfig, fixed_amount: float | None = None
) -> BacktestResult:
    engine = StrategyEngine(config)
    fixed = fixed_amount if fixed_amount is not None else config.base_amount
    state = StrategyState()
    result = BacktestResult()

    me = month_end_closes(close)
    for me_date in me.index:
        hist = close.loc[:me_date]
        if len(hist) < config.min_history_days:
            continue
        try:
            decision = engine.decide(close, state, as_of=me_date)
        except ValueError:
            continue  # 指标窗口不足，跳过
        state = engine.apply(state, decision)

        # 执行日 = 信号日之后的第一个交易日；回测末尾无下一交易日则跳过执行
        future = close.loc[close.index > me_date]
        if future.empty:
            exec_date, exec_price = None, None
        else:
            exec_date, exec_price = future.index[0], float(future.iloc[0])

        if decision.state == State.DOUBLE:
            result.months_double += 1
        elif decision.state == State.HALF:
            result.months_half += 1
        else:
            result.months_normal += 1

        record = {
            "month": decision.month,
            "signal_date": decision.decision_date,
            "exec_date": exec_date.strftime("%Y-%m-%d") if exec_date is not None else None,
            "state": decision.state.value,
            "amount": decision.amount,
            "exec_price": exec_price,
        }
        result.records.append(record)

        if exec_price is not None:
            result.total_invested += decision.amount
            result.fixed_total_invested += fixed
            result.strategy_shares += decision.amount / exec_price
            result.fixed_shares += fixed / exec_price

    result.final_price = float(close.iloc[-1]) if len(close) else 0.0
    return result
