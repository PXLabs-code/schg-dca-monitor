"""测试公共夹具：合成行情数据生成（不依赖实时行情）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from schg_monitor.config import StrategyConfig


def make_series(prices: list[float], start: str = "2022-01-03") -> pd.Series:
    """用美国交易日（工作日近似，含节假日剔除见具体测试）生成收盘价序列。"""
    idx = pd.bdate_range(start=start, periods=len(prices))
    return pd.Series(prices, index=idx, name="close", dtype=float)


def flat_then(n_flat: int, tail: list[float], base: float = 100.0, start: str = "2022-01-03") -> pd.Series:
    return make_series([base] * n_flat + tail, start=start)


@pytest.fixture
def config() -> StrategyConfig:
    return StrategyConfig()


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)
