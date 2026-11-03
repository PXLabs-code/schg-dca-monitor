"""主流程集成测试（使用模拟行情与模拟 Telegram，不访问网络）。"""

from __future__ import annotations

from dataclasses import replace
from unittest import mock

import pytest
from tests.conftest import make_series

from schg_monitor import main as main_mod
from schg_monitor.config import DEFAULT_CONFIG
from schg_monitor.data_provider import DataError, FetchResult


@pytest.fixture
def cfg(tmp_path):
    return replace(
        DEFAULT_CONFIG,
        data_dir=tmp_path,
        log_dir=tmp_path / "logs",
        cache_file=tmp_path / "cache.csv",
        state_file=tmp_path / "state.json",
        signals_file=tmp_path / "signals.json",
    )


def recent_series():
    """以今天为终点的 320 个交易日合成序列，保证决策月份=当前月份。"""
    import pandas as pd

    idx = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=320)
    return pd.Series([100.0 + i * 0.05 for i in range(320)], index=idx, name="close")


def patch_fetch(series):
    return mock.patch.object(
        main_mod.MarketDataService,
        "get_history",
        return_value=FetchResult(close=series, source="mock", fetched_at="2024-01-01T00:00:00"),
    )


def patch_send(ok=True):
    return mock.patch("schg_monitor.notifier.TelegramNotifier.send", return_value=ok)


class TestRunFlow:
    def test_run_records_signal_and_state(self, cfg):
        with patch_fetch(recent_series()), patch_send() as send:
            assert main_mod.cmd_run(cfg) == 0
            assert send.call_count == 1
        assert cfg.state_file.exists()
        assert cfg.signals_file.exists()

    def test_decision_targets_previous_month_end(self, cfg):
        """决策月份必须是上一个自然月（月末最后交易日数据），而非运行当月。"""
        import json
        from datetime import datetime, timedelta

        from schg_monitor.config import MARKET_TZ

        with patch_fetch(recent_series()), patch_send():
            assert main_mod.cmd_run(cfg) == 0
        prev = datetime.now(tz=MARKET_TZ).date().replace(day=1) - timedelta(days=1)
        signals = json.loads(cfg.signals_file.read_text())
        assert signals[0]["month"] == prev.strftime("%Y-%m")
        assert signals[0]["decision_date"] <= prev.isoformat()

    def test_same_month_second_run_skips(self, cfg):
        """同月第二次运行（launchd 重复触发/重启）不重复发送。"""
        with patch_fetch(recent_series()), patch_send() as send:
            main_mod.cmd_run(cfg)
            main_mod.cmd_run(cfg)
            assert send.call_count == 1

    def test_data_error_blocks_signal(self, cfg):
        """数据异常时禁止生成策略信号，仅发送告警。"""
        with mock.patch.object(
            main_mod.MarketDataService, "get_history", side_effect=DataError("boom")
        ), patch_send() as send:
            assert main_mod.cmd_run(cfg) == 1
        assert not cfg.signals_file.exists()
        # 发送的是数据异常告警而非策略信号
        sent_text = send.call_args.args[0]
        assert "数据异常" in sent_text

    def test_insufficient_history_no_signal(self, cfg):
        short = make_series([100.0] * 100)
        with patch_fetch(short), patch_send():
            assert main_mod.cmd_run(cfg) == 1
        assert not cfg.signals_file.exists()

    def test_telegram_failure_still_records(self, cfg):
        """Telegram 失败不影响信号记录，notified=False 可供诊断。"""
        import json

        with patch_fetch(recent_series()), patch_send(ok=False):
            assert main_mod.cmd_run(cfg) == 0
        signals = json.loads(cfg.signals_file.read_text())
        assert signals[0]["notified"] is False


class TestSecretsSafety:
    def test_token_never_logged(self, cfg, caplog):
        """日志中绝不出现 Token。"""
        import logging

        token = "123456:SECRET-TOKEN-VALUE"
        with mock.patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": "42"},
        ), patch_fetch(recent_series()), mock.patch("requests.post") as post:
            resp = mock.Mock(ok=True)
            resp.json.return_value = {"ok": True}
            post.return_value = resp
            with caplog.at_level(logging.DEBUG):
                main_mod.cmd_run(cfg)
        assert token not in caplog.text
        assert "SECRET-TOKEN-VALUE" not in caplog.text
