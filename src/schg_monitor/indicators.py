"""技术指标模块。

全部基于【交易日序列】（DataFrame 索引为交易日），使用调整收盘价，
所有 rolling 计算仅使用当前及过去数据，不引入未来数据。
"""

from __future__ import annotations

import pandas as pd


def rolling_max_close(close: pd.Series, window: int = 252) -> pd.Series:
    """过去 window 个交易日（含当日）的最高收盘价。

    min_periods=window：历史不足时为 NaN，避免用不完整窗口产生信号。
    """
    return close.rolling(window=window, min_periods=window).max()


def drawdown_pct(close: pd.Series, window: int = 252) -> pd.Series:
    """当前收盘价相对过去 window 日最高收盘价的回撤比例（正数表示下跌幅度）。"""
    peak = rolling_max_close(close, window)
    return (peak - close) / peak


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI，采用标准 Wilder 平滑算法。

    - 首个均值 = 前 period 个涨跌幅的简单平均（Wilder 原著种子值）。
    - 之后递推：avg = (prev_avg * (period - 1) + current) / period。
    - 前 period 个值为 NaN（数据不足）。
    """
    import numpy as np

    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return pd.Series(out, index=close.index)

    delta = close.diff().to_numpy()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = np.nanmean(gain[1 : period + 1])
    avg_loss = np.nanmean(loss[1 : period + 1])

    def _rsi(g: float, loss_val: float) -> float:
        if loss_val == 0:
            return 100.0
        rs = g / loss_val
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        out[i] = _rsi(avg_gain, avg_loss)
    return pd.Series(out, index=close.index)


def sma(close: pd.Series, window: int = 200) -> pd.Series:
    """简单移动平均线，历史不足时为 NaN。"""
    return close.rolling(window=window, min_periods=window).mean()


def sma_deviation(close: pd.Series, window: int = 200) -> pd.Series:
    """收盘价相对 SMA 的偏离率：(close - sma) / sma。"""
    ma = sma(close, window)
    return (close - ma) / ma


def month_end_closes(close: pd.Series) -> pd.Series:
    """每个自然月【最后一个有效交易日】的收盘价（索引为该交易日）。

    自动跳过节假日/周末：取每月实际存在数据的最后一个交易日。
    """
    df = close.dropna()
    grouped = df.groupby([df.index.year, df.index.month])
    idx = grouped.apply(lambda s: s.index[-1])
    return df.loc[idx.values]


def monthly_close_up(close: pd.Series) -> pd.Series:
    """当月最后交易日收盘价是否高于上月最后交易日收盘价。"""
    me = month_end_closes(close)
    return me > me.shift(1)
