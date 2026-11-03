#!/usr/bin/env bash
# SCHG DCA Monitor — 运行入口（手动或 launchd 调用）
# 用法: ./run.sh [run|backtest|test-telegram] [--force]
set -euo pipefail

cd "$(dirname "$0")"

# 加载 .env（不回显内容，避免泄漏密钥）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ ! -x .venv/bin/python ]; then
  echo "错误：未找到虚拟环境，请先运行 ./install.sh" >&2
  exit 1
fi

exec .venv/bin/python -m schg_monitor.main "${@:-run}"
