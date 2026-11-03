"""主程序入口。

用法：
    python -m schg_monitor.main run         # 月度策略检查（默认，幂等：同月只执行一次）
    python -m schg_monitor.main run --force # 忽略同月去重（仅用于手动测试）
    python -m schg_monitor.main backtest    # 历史回测
    python -m schg_monitor.main test-telegram  # 发送 Telegram 测试消息
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from datetime import datetime, timedelta

from .config import DEFAULT_CONFIG, MARKET_TZ, AppConfig, load_telegram_credentials
from .data_provider import DataError, MarketDataService, YFinanceProvider
from .notifier import TelegramNotifier, format_message
from .state_store import StateStore
from .strategy import StrategyEngine

logger = logging.getLogger("schg_monitor")


def setup_logging(cfg: AppConfig) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        cfg.log_dir / "monitor.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    console = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, console],
    )


def build_notifier(cfg: AppConfig) -> TelegramNotifier:
    token, chat_id = load_telegram_credentials()
    return TelegramNotifier(token, chat_id, retries=cfg.telegram_retries, retry_wait=cfg.telegram_retry_wait)


def cmd_run(cfg: AppConfig, force: bool = False) -> int:
    """月度策略检查。

    设计为每月 1 日（含 2/3 日作为补偿）由 launchd 触发：
    使用【上一个自然月的最后一个有效交易日】数据决策，
    与"月末最后交易日决策"规则严格一致；同月幂等，不重复通知。
    """
    import pandas as pd

    store = StateStore(cfg.state_file, cfg.signals_file)
    engine = StrategyEngine(cfg.strategy)
    service = MarketDataService(
        YFinanceProvider(cfg.fetch_retries, cfg.fetch_retry_wait), cfg.cache_file
    )

    now = datetime.now(tz=MARKET_TZ)
    prev_month_end = now.date().replace(day=1) - timedelta(days=1)
    target_month = prev_month_end.strftime("%Y-%m")
    if not force and store.has_signal_for_month(target_month):
        logger.info("月份 %s 信号已生成，跳过（幂等保护，防止重复通知）", target_month)
        return 0

    try:
        fetch = service.get_history(cfg.strategy.symbol, cfg.strategy.min_history_days)
    except DataError as exc:
        logger.error("数据异常，禁止生成策略信号：%s", exc)
        notifier = build_notifier(cfg)
        notifier.send(f"⚠️ *SCHG 监控数据异常*\n\n{exc}\n\n本月未生成策略信号，请人工检查。")
        return 1

    # 决策时点 = 上月最后一个有效交易日（自动跳过节假日/周末）
    hist_until = fetch.close.loc[: pd.Timestamp(prev_month_end)]
    if hist_until.empty:
        logger.error("行情数据不包含 %s 之前的数据，无法决策", prev_month_end)
        return 1
    as_of = hist_until.index[-1]

    state = store.load_state()
    try:
        decision = engine.decide(fetch.close, state, as_of=as_of)
    except ValueError as exc:
        logger.error("指标计算失败：%s", exc)
        return 1

    if not force and store.has_signal_for_month(decision.month):
        logger.info("月份 %s 信号已存在，跳过重复记录", decision.month)
        return 0

    message = format_message(decision, fetch.source, fetch.fetched_at)
    notifier = build_notifier(cfg)
    notified = notifier.send(message)

    new_state = engine.apply(state, decision)
    store.save_state(new_state)
    recorded = store.record_signal(decision, notified, extra={"data_source": fetch.source})
    logger.info(
        "决策完成：%s 月 状态=%s 金额=%.0f USD 已通知=%s 已记录=%s",
        decision.month, decision.state.value, decision.amount, notified, recorded,
    )
    print(message)
    return 0


def cmd_backtest(cfg: AppConfig) -> int:
    from .backtest import run_backtest

    service = MarketDataService(
        YFinanceProvider(cfg.fetch_retries, cfg.fetch_retry_wait), cfg.cache_file
    )
    try:
        fetch = service.get_history(cfg.strategy.symbol, cfg.strategy.min_history_days)
    except DataError as exc:
        logger.error("数据异常：%s", exc)
        return 1
    result = run_backtest(fetch.close, cfg.strategy)
    print(result.summary())
    print("\n每月明细：")
    for r in result.records:
        print(
            f"  {r['month']}  信号日 {r['signal_date']}  执行日 {r['exec_date']}"
            f"  {r['state']:<6}  {r['amount']:>6.0f} USD  @ {r['exec_price']}"
        )
    return 0


def cmd_test_telegram(cfg: AppConfig) -> int:
    notifier = build_notifier(cfg)
    if not notifier.configured:
        print("错误：请先设置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 环境变量", file=sys.stderr)
        return 1
    ok = notifier.send(
        "✅ *SCHG DCA Monitor 测试消息*\n\nTelegram 通知链路正常。\n_本系统仅提供监控提醒，不执行任何交易。_"
    )
    print("发送成功" if ok else "发送失败")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schg-dca-monitor")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="执行月度策略检查")
    run_p.add_argument("--force", action="store_true", help="忽略同月去重（仅测试用）")
    sub.add_parser("backtest", help="历史回测")
    sub.add_parser("test-telegram", help="发送 Telegram 测试消息")
    args = parser.parse_args(argv)

    cfg = DEFAULT_CONFIG
    setup_logging(cfg)

    if args.command == "backtest":
        return cmd_backtest(cfg)
    if args.command == "test-telegram":
        return cmd_test_telegram(cfg)
    return cmd_run(cfg, force=getattr(args, "force", False))


if __name__ == "__main__":
    sys.exit(main())
