#!/usr/bin/env bash
# SCHG DCA Monitor — macOS 安装脚本
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "==> 检查 Python 版本（需要 3.12+）..."
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), f"需要 Python 3.12+，当前 {sys.version}"'

echo "==> 创建虚拟环境 .venv ..."
"$PYTHON" -m venv .venv

echo "==> 安装依赖 ..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

mkdir -p data logs

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> 已生成 .env，请编辑填入 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID"
fi

echo ""
echo "安装完成！后续步骤："
echo "  1. 编辑 .env 填入 Telegram 凭据"
echo "  2. 测试通知：    ./run.sh test-telegram"
echo "  3. 手动运行：    ./run.sh run"
echo "  4. 历史回测：    ./run.sh backtest"
echo "  5. 配置定时任务：见 README 的 launchd 部署章节"
