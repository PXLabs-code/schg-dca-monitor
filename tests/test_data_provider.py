"""数据提供商模块测试：缺失数据、API 失败、缓存回退、数据校验。"""

from __future__ import annotations

import pandas as pd
import pytest
from tests.conftest import make_series

from schg_monitor.data_provider import (
    DataError,
    MarketDataService,
    validate_history,
)


class FailingProvider:
    name = "failing"

    def fetch_history(self, symbol, min_days):
        raise DataError("模拟 API 请求失败")


class GoodProvider:
    name = "good"

    def __init__(self, series):
        self.series = series

    def fetch_history(self, symbol, min_days):
        return validate_history(self.series, min_days)


class TestValidate:
    def test_empty_raises(self):
        with pytest.raises(DataError, match="为空"):
            validate_history(pd.Series(dtype=float), 300)

    def test_too_short_raises(self):
        s = make_series([100.0] * 100)
        with pytest.raises(DataError, match="不足"):
            validate_history(s, 300)

    def test_nan_dropped(self):
        s = make_series([100.0] * 310)
        s.iloc[5] = float("nan")
        out = validate_history(s, 300)
        assert not out.isna().any()
        assert len(out) == 309

    def test_nan_causing_shortage_raises(self):
        s = make_series([float("nan")] * 50 + [100.0] * 260)
        with pytest.raises(DataError):
            validate_history(s, 300)

    def test_negative_price_raises(self):
        s = make_series([100.0] * 310)
        s.iloc[0] = -1.0
        with pytest.raises(DataError, match="非正"):
            validate_history(s, 300)

    def test_duplicates_removed(self):
        s = make_series([100.0] * 310)
        s2 = pd.concat([s, s.iloc[[-1]]])
        out = validate_history(s2, 300)
        assert not out.index.duplicated().any()


class TestMarketDataService:
    def test_fetch_failure_without_cache_raises(self, tmp_path):
        svc = MarketDataService(FailingProvider(), tmp_path / "cache.csv")
        with pytest.raises(DataError):
            svc.get_history("SCHG", 300)

    def test_cache_written_and_fallback(self, tmp_path):
        s = make_series([100.0 + i for i in range(310)])
        cache = tmp_path / "cache.csv"
        ok = MarketDataService(GoodProvider(s), cache)
        res1 = ok.get_history("SCHG", 300)
        assert cache.exists()
        assert res1.source == "good"
        # 元数据记录来源与更新时间
        meta = cache.with_suffix(".meta").read_text()
        assert "source=good" in meta
        assert "fetched_at=" in meta

        # API 失败 → 回退缓存
        bad = MarketDataService(FailingProvider(), cache)
        res2 = bad.get_history("SCHG", 300)
        assert "cache" in res2.source
        assert len(res2.close) == 310

    def test_fallback_disabled(self, tmp_path):
        s = make_series([100.0] * 310)
        cache = tmp_path / "cache.csv"
        MarketDataService(GoodProvider(s), cache).get_history("SCHG", 300)
        bad = MarketDataService(FailingProvider(), cache)
        with pytest.raises(DataError):
            bad.get_history("SCHG", 300, allow_cache_fallback=False)

    def test_short_cache_not_used(self, tmp_path):
        """缓存数据不足 300 日时不得作为回退，必须抛出 DataError。"""
        s = make_series([100.0] * 50)
        cache = tmp_path / "cache.csv"
        svc = MarketDataService(FailingProvider(), cache)
        svc._save_cache(s, "2024-01-01T00:00:00")
        with pytest.raises(DataError):
            svc.get_history("SCHG", 300)
