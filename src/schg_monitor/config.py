"""集中配置模块。

所有策略阈值集中在此处，业务代码不得硬编码任何阈值。
密钥（Telegram Token 等）仅通过环境变量读取，严禁写入代码或日志。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

# 美国市场时区（自动处理夏令时）
MARKET_TZ = ZoneInfo("America/New_York")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StrategyConfig:
    """策略参数（单一事实来源）。"""

    symbol: str = "SCHG"

    # 定投金额（USD/月）
    base_amount: float = 2000.0
    double_amount: float = 4000.0
    half_amount: float = 1000.0

    # 加倍条件
    drawdown_threshold: float = 0.20          # 回撤 >= 20%（相对 252 日最高收盘价）
    lookback_high_window: int = 252           # 交易日窗口
    double_max_months: int = 3                # 加倍最多持续 3 个月

    # 减半条件
    rsi_overbought: float = 75.0              # RSI(14) >= 75
    sma_deviation_threshold: float = 0.15     # 偏离 SMA200 >= 15%

    # 减半恢复条件
    rsi_recovery: float = 65.0                # RSI(14) < 65
    sma_deviation_recovery: float = 0.10      # 偏离 SMA200 <= 10%

    # 指标参数
    rsi_period: int = 14
    sma_window: int = 200

    # 数据要求
    min_history_days: int = 300               # 至少 300 个交易日
    # 行情统一使用【调整收盘价】(adjusted close, auto_adjust=True)，
    # 所有指标计算口径保持一致。
    use_adjusted_close: bool = True


@dataclass(frozen=True)
class AppConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "logs"
    cache_file: Path = PROJECT_ROOT / "data" / "schg_history.csv"
    state_file: Path = PROJECT_ROOT / "data" / "state.json"
    signals_file: Path = PROJECT_ROOT / "data" / "signals.json"

    # 网络重试
    fetch_retries: int = 3
    fetch_retry_wait: float = 5.0
    telegram_retries: int = 3
    telegram_retry_wait: float = 3.0


def load_telegram_credentials() -> tuple[str | None, str | None]:
    """仅从环境变量读取 Telegram 凭据，绝不写入日志。"""
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


DEFAULT_CONFIG = AppConfig()
