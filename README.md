# SCHG DCA Monitor

SCHG（Schwab U.S. Large-Cap Growth ETF）定投量化监控系统。每月自动获取行情、计算技术指标、根据策略状态机决定定投金额，并通过 Telegram Bot 发送中文策略提醒。

> ⚠️ **本系统仅提供投资辅助监控与提醒，不执行任何自动买卖交易。**

[![CI](https://github.com/PXLabs-code/schg-dca-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/PXLabs-code/schg-dca-monitor/actions/workflows/ci.yml)

## 功能

- 自动获取 SCHG 历史行情（≥300 交易日，Yahoo Finance，**调整收盘价**口径，本地缓存 + 失败重试 + 缓存回退）
- 技术指标：RSI(14)（标准 Wilder 平滑）、SMA(200)、252 日滚动最高收盘价、回撤比例、均线偏离率、月末收盘环比
- 三状态策略状态机（正常 / 加倍 / 减半），防重复触发、同月幂等
- Telegram 中文 Markdown 通知，发送失败重试，发送状态持久化
- 历史回测（无未来数据；信号在月末生成、下一交易日执行）
- macOS launchd 定时运行，日志轮转

## 策略规则

所有决策基于**每月最后一个有效交易日**的数据（自动跳过周末与美国节假日）。所有阈值集中在 [`src/schg_monitor/config.py`](src/schg_monitor/config.py)。

| 状态 | 条件 | 金额 |
|---|---|---|
| **加倍** | 相对 252 日最高收盘价回撤 ≥ 20% **且** 当月末收盘 > 上月末收盘 | 4000 USD/月（最多连续 3 个月，之后强制恢复） |
| **正常** | 不满足加倍与减半条件 | 2000 USD/月 |
| **减半** | RSI(14) ≥ 75 **且** 收盘价偏离 SMA(200) ≥ +15% | 1000 USD/月 |
| **减半恢复** | RSI(14) < 65 **且** 偏离 ≤ +10%（满足一个月） | 恢复 2000 USD/月 |

- **优先级：减半 > 加倍**（同时满足时执行减半）
- 不设 SCHG 持仓比例上限；不根据日内行情改变月度策略
- 边界值均为闭区间触发（恰好 20% / 75 / 15% 即触发；恢复条件恰好 10% 即满足）

### 运行时序

launchd 在每月 **1/2/3 日 09:30（本地时间）** 触发（多日仅为补偿关机/睡眠，程序按月幂等）。程序使用**上一自然月最后一个有效交易日**的数据决策——即"月末决策、次月初通知/执行"，回测同样假设信号生成后的下一个交易日执行，避免未来数据。

## 目录结构

```
src/schg_monitor/
  config.py          # 全部阈值与路径的单一配置来源
  data_provider.py   # 行情数据（可替换 Provider 协议 + 缓存 + 重试）
  indicators.py      # 技术指标（独立单元测试覆盖）
  strategy.py        # 策略引擎 / 状态机
  state_store.py     # 状态与信号持久化（JSON，幂等去重）
  notifier.py        # Telegram 通知与消息格式化
  backtest.py        # 历史回测
  main.py            # CLI 入口
tests/               # 78 个自动化测试（全部使用模拟数据）
deploy/launchd/      # macOS 定时任务配置
.github/workflows/   # CI（Ruff + Pytest + 密钥扫描）
```

## macOS 安装

要求：macOS、Python 3.12+（`brew install python@3.12`）。

```bash
git clone https://github.com/PXLabs-code/schg-dca-monitor.git
cd schg-dca-monitor
git checkout copilot/initial-implementation
./install.sh
```

### Telegram 配置

1. 在 Telegram 中与 [@BotFather](https://t.me/BotFather) 对话，`/newbot` 创建机器人，获得 **Bot Token**。
2. 与新机器人发一条消息，然后访问 `https://api.telegram.org/bot<TOKEN>/getUpdates`，从返回 JSON 中读取 `chat.id` 作为 **Chat ID**。
3. 编辑项目根目录 `.env`：

```bash
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_CHAT_ID=987654321
```

> `.env` 已被 `.gitignore` 排除；CI 中的 gitleaks 会拦截任何误提交的密钥。**严禁将 Token 写入代码或日志。**

### 验证

```bash
./run.sh test-telegram   # 应收到测试消息
./run.sh run             # 手动执行一次月度检查（同月重复运行会自动跳过）
./run.sh run --force     # 测试用：忽略同月去重
./run.sh backtest        # 历史回测统计
```

### 定时任务（launchd）

```bash
./deploy/launchd/setup_launchd.sh
```

- 查看状态：`launchctl print gui/$(id -u)/com.schg.dca-monitor`
- 立即触发：`launchctl kickstart gui/$(id -u)/com.schg.dca-monitor`
- 卸载：`launchctl bootout gui/$(id -u)/com.schg.dca-monitor`

时区：交易日判断统一使用 `America/New_York`（自动处理夏令时）。launchd 触发时间为 Mac 本地时间，因程序按月幂等，时差不影响正确性。

### 日志与诊断

- 应用日志：`logs/monitor.log`（RotatingFileHandler，1MB × 5 份自动轮转）
- launchd 输出：`logs/launchd.out.log` / `logs/launchd.err.log`
- 状态：`data/state.json`；历史信号：`data/signals.json`；行情缓存：`data/schg_history.csv`（`.meta` 记录数据来源与更新时间）
- 程序重启/重复运行不会重复发送同一月份的通知（以 `signals.json` 为准）

## 数据口径说明

- 全部使用 **调整收盘价**（yfinance `auto_adjust=True`），指标计算口径一致
- 仅使用交易日数据；缺失值剔除；历史不足 300 交易日时拒绝生成信号
- 所有 rolling 指标 `min_periods=window`，窗口不足即为 NaN，**不使用未来数据**
- 数据获取失败：重试 3 次 → 回退本地缓存 → 仍失败则**不生成信号**并发送数据异常告警

## 开发与测试

```bash
pip install -e ".[dev]"
ruff check .
pytest -v
```

测试覆盖：RSI（含 Wilder 原著对照值）、回撤、SMA、月末比较、全部状态转换、边界值（恰好 20%/75/15%/10%）、双条件冲突、加倍 3 个月上限、减半恢复、数据缺失、API 失败、Telegram 失败重试、同月重复执行、美国节假日、重启幂等。CI 不访问真实行情、不发送真实 Telegram 消息。

## 免责声明

本项目仅用于个人投资流程辅助监控，不构成投资建议，不执行任何证券交易。
