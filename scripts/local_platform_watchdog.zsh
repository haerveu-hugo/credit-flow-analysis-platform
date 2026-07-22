#!/bin/zsh
setopt NO_BG_NICE 2>/dev/null || true

ROOT="/Users/haerveu/Documents/Codex/2026-06-24/wo"
PY="/Users/haerveu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
STATE_DIR="/Users/haerveu/Library/Application Support/HaerveuAnalysis"
LOG="$STATE_DIR/local-analysis-platform-watchdog.log"
SERVER_LOG="$STATE_DIR/local-analysis-platform-services.log"

mkdir -p "$STATE_DIR"
cd "$ROOT" || exit 1

responds() {
  local URL="$1"
  curl -fsS --max-time 3 "$URL" >/dev/null 2>&1
}

port_pids() {
  local PORT="$1"
  lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

start_service() {
  local NAME="$1"
  local PORT="$2"
  local URL="$3"
  local SCRIPT="$4"
  local PIDFILE="$5"

  if responds "$URL"; then
    return 0
  fi

  local OLD_PIDS
  OLD_PIDS="$(port_pids "$PORT")"
  if [ -n "$OLD_PIDS" ]; then
    for PID in ${(f)OLD_PIDS}; do
      kill "$PID" 2>/dev/null || true
    done
    sleep 1
  fi

  {
    echo ""
    echo "==== $(date '+%Y-%m-%d %H:%M:%S') watchdog start $NAME ===="
    echo "PORT=$PORT URL=$URL SCRIPT=$SCRIPT"
  } >> "$LOG"

  PORT="$PORT" nohup "$PY" "$SCRIPT" >> "$SERVER_LOG" 2>&1 &
  local PID="$!"
  disown "$PID" 2>/dev/null || true
  echo "$PID" > "$PIDFILE"

  for i in {1..20}; do
    if responds "$URL"; then
      echo "$NAME OK pid=$PID url=$URL" >> "$LOG"
      return 0
    fi
    sleep 1
  done

  echo "$NAME failed to respond: $URL" >> "$LOG"
  return 1
}

while true; do
  start_service "征信分析" 8789 "http://127.0.0.1:8789/" "work/credit_local_server.py" "$STATE_DIR/credit_platform_8789.pid"
  start_service "流水统计" 8790 "http://127.0.0.1:8790/flow" "work/flow_local_server.py" "$STATE_DIR/flow_platform.pid"
  start_service "综合分析" 8792 "http://127.0.0.1:8792/comprehensive" "work/comprehensive_local_server.py" "$STATE_DIR/comprehensive_platform_8792.pid"
  start_service "财报分析" 8793 "http://127.0.0.1:8793/financial" "work/financial_local_server.py" "$STATE_DIR/financial_platform_8793.pid"
  start_service "统一入口" 8791 "http://127.0.0.1:8791/" "work/hub_local_server.py" "$STATE_DIR/hub_platform_8791.pid"
  sleep 30
done
