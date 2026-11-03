"""Telegram 通知模块与消息格式化。

- 凭据仅来自环境变量，绝不写入日志。
- 支持 Markdown、中文、发送失败重试、发送状态记录。
- 仅发送提醒，不执行任何交易。
"""

from __future__ import annotations

import logging
import time

import requests

from .strategy import Decision, State

logger = logging.getLogger(__name__)

_TITLES = {
    State.DOUBLE: "SCHG 定投策略提醒：加倍",
    State.NORMAL: "SCHG 定投策略提醒：正常",
    State.HALF: "SCHG 定投策略提醒：减半",
}


def format_message(decision: Decision, source: str = "", fetched_at: str = "") -> str:
    """生成 Markdown 格式的中文策略报告。"""
    d = decision
    title = _TITLES[d.state]
    lines = [f"*{title}*", ""]
    lines += [
        f"📅 决策日期：{d.decision_date}（{d.month} 月末最后交易日）",
        f"💰 *建议定投金额：{d.amount:,.0f} USD*",
        "",
        f"收盘价：{d.close:,.2f} USD",
        f"252 日最高收盘价：{d.high_252:,.2f} USD",
        f"当前回撤：{d.drawdown:.2%}",
        f"RSI(14)：{d.rsi14:.1f}",
        f"SMA(200)：{d.sma200:,.2f} USD",
        f"均线偏离率：{d.sma_dev:+.2%}",
        f"月度收盘环比：{'上涨' if d.monthly_up else '未上涨'}",
        "",
        f"当前状态：{d.state.value}（已持续 {d.months_in_state} 个月）",
        "触发原因：",
    ]
    lines += [f"• {r}" for r in d.reasons]
    if d.state == State.HALF:
        lines += [
            "",
            "恢复条件：RSI(14) < 65 且 均线偏离率 <= 10%（满足一个月后恢复 2000 USD/月）",
        ]
    lines += ["", f"下次检查日期：{d.next_check_date}"]
    if source:
        lines.append(f"数据来源：{source}（更新于 {fetched_at[:19]}）")
    lines += ["", "_本系统仅提供监控提醒，不执行任何交易。_"]
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
        retries: int = 3,
        retry_wait: float = 3.0,
        timeout: float = 15.0,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.retries = retries
        self.retry_wait = retry_wait
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        """发送消息，带重试；返回是否成功。日志中绝不输出 Token。"""
        if not self.configured:
            logger.warning("Telegram 未配置（缺少环境变量），跳过发送")
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.ok and resp.json().get("ok"):
                    logger.info("Telegram 发送成功（第 %d 次尝试）", attempt)
                    return True
                logger.warning(
                    "Telegram 发送失败（第 %d/%d 次）：HTTP %s",
                    attempt, self.retries, resp.status_code,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Telegram 请求异常（第 %d/%d 次）：%s",
                    attempt, self.retries, type(exc).__name__,
                )
            if attempt < self.retries:
                time.sleep(self.retry_wait)
        logger.error("Telegram 发送最终失败（已重试 %d 次）", self.retries)
        return False
