#!/bin/zsh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

for pid_file in tmp/*.pid; do
  [[ -f "$pid_file" ]] || continue
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "停止进程：$pid"
    kill "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
done

echo "已停止本地分析平台。"
