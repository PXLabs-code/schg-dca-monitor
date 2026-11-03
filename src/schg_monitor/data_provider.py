"""行情数据提供商模块。

与策略计算解耦：策略引擎只接受 `pd.Series`（交易日索引的调整收盘价）。
默认实现基于 yfinance（Yahoo Finance），可替换为任意实现 `DataProvider`
协议的提供商。支持本地 CSV 缓存、失败重试、数据完整性校验。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from .config import MARKET_TZ

logger = logging.getLogger(__name__)


class DataError(Exception):
    """数据获取/校验失败。出现此异常时禁止生成新的有效策略信号。"""


class DataProvider(Protocol):
    def fetch_history(self, symbol: str, min_days: int) -> pd.Series:
        """返回按交易日升序索引的调整收盘价序列。"""
        ...


@dataclass
class FetchResult:
    close: pd.Series          # 调整收盘价，DatetimeIndex（交易日，无时区，America/New_York 口径）
    source: str
    fetched_at: str           # ISO 时间戳


def validate_history(close: pd.Series, min_days: int) -> pd.Series:
    """校验与清洗：去缺失、排序、去重、检查长度与数值合法性。"""
    if close is None or len(close) == 0:
        raise DataError("行情数据为空")
    s = close.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if (s <= 0).any():
        raise DataError("行情数据包含非正价格")
    if len(s) < min_days:
        raise DataError(f"历史数据不足：需要至少 {min_days} 个交易日，实际 {len(s)}")
    return s


class YFinanceProvider:
    """Yahoo Finance 提供商（auto_adjust=True，即调整收盘价）。"""

    name = "yfinance"

    def __init__(self, retries: int = 3, retry_wait: float = 5.0) -> None:
        self.retries = retries
        self.retry_wait = retry_wait

    def fetch_history(self, symbol: str, min_days: int) -> pd.Series:
        import yfinance as yf

        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                df = yf.download(
                    symbol,
                    period="3y",
                    interval="1d",
                    auto_adjust=True,  # 调整收盘价，口径与指标计算一致
                    progress=False,
                )
                if df is None or df.empty:
                    raise DataError("yfinance 返回空数据")
                close = df["Close"]
                if isinstance(close, pd.DataFrame):  # 多级列
                    close = close.iloc[:, 0]
                close.index = pd.DatetimeIndex(close.index).tz_localize(None)
                close.name = "close"
                return validate_history(close, min_days)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning("第 %d/%d 次获取行情失败: %s", attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(self.retry_wait)
        raise DataError(f"行情获取失败（已重试 {self.retries} 次）: {last_err}")


class MarketDataService:
    """带本地缓存的数据服务。"""

    def __init__(
        self,
        provider: DataProvider,
        cache_file: Path,
        provider_name: str = "unknown",
    ) -> None:
        self.provider = provider
        self.cache_file = cache_file
        self.provider_name = getattr(provider, "name", provider_name)

    def _save_cache(self, close: pd.Series, fetched_at: str) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        df = close.to_frame("close")
        df.index.name = "date"
        df.attrs = {}
        df.to_csv(self.cache_file)
        meta = self.cache_file.with_suffix(".meta")
        meta.write_text(f"source={self.provider_name}\nfetched_at={fetched_at}\n")

    def load_cache(self) -> pd.Series | None:
        if not self.cache_file.exists():
            return None
        try:
            df = pd.read_csv(self.cache_file, index_col="date", parse_dates=True)
            return df["close"]
        except Exception:  # noqa: BLE001
            logger.warning("缓存文件损坏，忽略缓存")
            return None

    def get_history(self, symbol: str, min_days: int, allow_cache_fallback: bool = True) -> FetchResult:
        fetched_at = datetime.now(tz=MARKET_TZ).isoformat()
        try:
            close = self.provider.fetch_history(symbol, min_days)
            self._save_cache(close, fetched_at)
            logger.info("行情获取成功：%d 个交易日，来源=%s", len(close), self.provider_name)
            return FetchResult(close=close, source=self.provider_name, fetched_at=fetched_at)
        except DataError:
            if allow_cache_fallback:
                cached = self.load_cache()
                if cached is not None:
                    try:
                        close = validate_history(cached, min_days)
                        logger.warning("在线获取失败，使用本地缓存（可能过期）")
                        return FetchResult(
                            close=close,
                            source=f"{self.provider_name}(cache)",
                            fetched_at=fetched_at,
                        )
                    except DataError:
                        pass
            raise
