#!/usr/bin/env bash
# 安装 launchd 定时任务（macOS）
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="$PROJECT_DIR/deploy/launchd/com.schg.dca-monitor.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.schg.dca-monitor.plist"
LABEL="com.schg.dca-monitor"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

# 重新加载
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "launchd 任务已安装：$PLIST_DST"
echo "查看状态： launchctl print gui/$(id -u)/$LABEL | head -20"
echo "立即测试： launchctl kickstart gui/$(id -u)/$LABEL"
echo "卸载任务： launchctl bootout gui/$(id -u)/$LABEL && rm $PLIST_DST"
