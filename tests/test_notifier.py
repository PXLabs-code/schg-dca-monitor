"""Telegram 通知测试：消息格式、发送失败重试、未配置跳过。不访问真实 API。"""

from __future__ import annotations

from unittest import mock

import pytest

from schg_monitor.notifier import TelegramNotifier, format_message
from schg_monitor.strategy import Decision, State


def make_decision(state=State.NORMAL, amount=2000.0) -> Decision:
    return Decision(
        month="2024-06",
        decision_date="2024-06-28",
        state=state,
        amount=amount,
        close=95.12,
        rsi14=55.3,
        sma200=90.45,
        high_252=110.00,
        drawdown=0.1353,
        sma_dev=0.0516,
        monthly_up=True,
        months_in_state=1,
        reasons=["正常定投：未触发加倍或减半条件"],
        next_check_date="2024-07-31",
    )


class TestMessageFormat:
    def test_normal_title_and_amount(self):
        msg = format_message(make_decision())
        assert "SCHG 定投策略提醒：正常" in msg
        assert "2,000 USD" in msg

    def test_double_message_contents(self):
        d = make_decision(State.DOUBLE, 4000.0)
        d.reasons = ["加倍触发：252 日回撤 25.0% >= 20% 且 当月末收盘高于上月末"]
        msg = format_message(d)
        assert "SCHG 定投策略提醒：加倍" in msg
        assert "4,000 USD" in msg
        assert "252 日最高收盘价" in msg
        assert "当前回撤" in msg
        assert "RSI(14)" in msg
        assert "SMA(200)" in msg
        assert "已持续 1 个月" in msg

    def test_half_message_has_recovery_condition(self):
        d = make_decision(State.HALF, 1000.0)
        msg = format_message(d)
        assert "SCHG 定投策略提醒：减半" in msg
        assert "1,000 USD" in msg
        assert "恢复条件" in msg
        assert "均线偏离率" in msg

    def test_markdown_and_chinese(self):
        msg = format_message(make_decision())
        assert msg.startswith("*")  # Markdown 加粗标题
        assert "不执行任何交易" in msg

    def test_no_token_in_message(self):
        msg = format_message(make_decision())
        assert "TOKEN" not in msg.upper() or "BOT" not in msg.upper()


class TestSend:
    def test_not_configured_returns_false(self):
        n = TelegramNotifier(None, None)
        assert n.send("hello") is False

    def test_success(self):
        n = TelegramNotifier("tok", "chat", retries=3, retry_wait=0)
        resp = mock.Mock(ok=True)
        resp.json.return_value = {"ok": True}
        with mock.patch("requests.post", return_value=resp) as post:
            assert n.send("hi") is True
            assert post.call_count == 1

    def test_retry_then_success(self):
        n = TelegramNotifier("tok", "chat", retries=3, retry_wait=0)
        bad = mock.Mock(ok=False, status_code=500)
        good = mock.Mock(ok=True)
        good.json.return_value = {"ok": True}
        with mock.patch("requests.post", side_effect=[bad, good]) as post:
            assert n.send("hi") is True
            assert post.call_count == 2

    def test_all_retries_fail(self):
        import requests as req

        n = TelegramNotifier("tok", "chat", retries=3, retry_wait=0)
        with mock.patch("requests.post", side_effect=req.ConnectionError) as post:
            assert n.send("hi") is False
            assert post.call_count == 3

    @pytest.mark.parametrize("state", [State.NORMAL, State.DOUBLE, State.HALF])
    def test_payload_uses_markdown(self, state):
        n = TelegramNotifier("tok", "chat", retries=1, retry_wait=0)
        resp = mock.Mock(ok=True)
        resp.json.return_value = {"ok": True}
        with mock.patch("requests.post", return_value=resp) as post:
            n.send(format_message(make_decision(state)))
            payload = post.call_args.kwargs["json"]
            assert payload["parse_mode"] == "Markdown"
            assert payload["chat_id"] == "chat"
