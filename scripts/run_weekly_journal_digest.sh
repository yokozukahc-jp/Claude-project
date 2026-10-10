#!/bin/bash
# 毎週土曜に launchd から呼ばれるラッパー。NEJM / Lancet の最新号をまとめる。
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/journal-digest"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d).log"

# API キーなどは設定ファイルから読む(launchd は通常のシェル環境を継承しないため)
[ -f "$HOME/.journal-digest.env" ] && . "$HOME/.journal-digest.env"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 ====="
  /usr/bin/python3 "$DIR/fetch_journal_abstracts.py" "$@"
  status=$?
  echo "===== 終了 (exit=$status) ====="
  exit $status
} >>"$LOG" 2>&1
