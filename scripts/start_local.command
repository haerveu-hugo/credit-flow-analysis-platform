#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p tmp logs outputs

PYTHON_BASE="${PYTHON_BASE:-python3}"
if [[ ! -d ".venv" ]]; then
  echo "首次运行：正在创建本地 Python 环境..."
  "$PYTHON_BASE" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

start_service() {
  local name="$1"
  local port="$2"
  local script="$3"
  local url="$4"
  local log_file="logs/${name}-${port}.log"
  local pid_file="tmp/${name}-${port}.pid"

  if curl -fsS "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
    echo "已运行：${name} ${url}"
    return
  fi

  echo "启动：${name} ${url}"
  PORT="$port" python "$script" > "$log_file" 2>&1 &
  echo $! > "$pid_file"
}

start_service "credit" 8789 "work/credit_local_server.py" "http://127.0.0.1:8789/"
start_service "flow" 8790 "work/flow_local_server.py" "http://127.0.0.1:8790/"
start_service "hub" 8791 "work/hub_local_server.py" "http://127.0.0.1:8791/"
start_service "comprehensive" 8792 "work/comprehensive_local_server.py" "http://127.0.0.1:8792/comprehensive"
start_service "financial" 8793 "work/financial_local_server.py" "http://127.0.0.1:8793/financial"

sleep 1
open "http://127.0.0.1:8791/"
echo "本地分析平台已打开：http://127.0.0.1:8791/"
