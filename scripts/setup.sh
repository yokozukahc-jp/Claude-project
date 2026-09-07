#!/bin/bash
# Mac で週次自動実行を有効にする。冪等なので再実行しても安全。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="jp.cardio.weekly-digest"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "$(uname)" != "Darwin" ]; then
  echo "このセットアップは macOS 専用です。" >&2
  exit 1
fi

echo "▶ 依存パッケージを導入します"
/usr/bin/python3 -m pip install --user --quiet --upgrade openpyxl

echo "▶ LaunchAgent を配置します: $DEST"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__SCRIPT_PATH__|$REPO/scripts/run_weekly.sh|" \
    "$REPO/launchd/$LABEL.plist" > "$DEST"

echo "▶ 既存の登録があれば解除して読み込み直します"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$DEST"

echo
echo "✅ 完了。毎週土曜 7:12 に実行されます。"
echo "   次回予定の確認 : launchctl print gui/$UID/$LABEL | grep -A3 'next fire'"
echo "   今すぐ試す     : launchctl kickstart -p gui/$UID/$LABEL"
echo "   停止           : launchctl bootout gui/$UID/$LABEL"
echo
if [ ! -f "$HOME/.cardio-digest.env" ]; then
  echo "⚠️  日本語訳を有効にするには ~/.cardio-digest.env を作成してください:"
  echo "      echo 'export ANTHROPIC_API_KEY=sk-ant-...' > ~/.cardio-digest.env"
fi
