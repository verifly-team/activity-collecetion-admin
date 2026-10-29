#!/usr/bin/env bash
# 一键跑 demo：自动建虚拟环境、装依赖、造数据、起服务
#
#   ./run-demo.sh                  # 本机预览，端口 8010
#   PORT=8011 ./run-demo.sh        # 换端口
#   HOST=0.0.0.0 ./run-demo.sh     # 允许外部访问（服务器上用）
#   NO_KILL=1 ./run-demo.sh        # 端口被占用时不自动清理，直接报错退出
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8010}"
HOST="${HOST:-127.0.0.1}"
PY="${PYTHON:-python3}"
NO_KILL="${NO_KILL:-0}"

# ---------------------------------------------------------------- 端口占用清理
port_pids() {
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:${port}" 2>/dev/null || true
  else
    ss -lntp 2>/dev/null | awk -v p=":${port}\$" '$4 ~ p {print $NF}' \
      | sed -E 's/.*pid=([0-9]+).*/\1/' | sort -u | grep -v '^$' || true
  fi
}

free_port() {
  local port=$1
  local pids
  pids=$(port_pids "$port")
  [ -z "$pids" ] && return 0

  if [ "$NO_KILL" = "1" ]; then
    echo "!! 端口 ${port} 已被占用（NO_KILL=1，不自动清理）"
    echo "   占用进程："
    for pid in $pids; do ps -p "$pid" -o pid=,command= 2>/dev/null | cut -c1-100; done
    exit 1
  fi

  echo "==> 端口 ${port} 被占用，正在关闭："
  for pid in $pids; do
    desc=$(ps -p "$pid" -o command= 2>/dev/null | cut -c1-90 || true)
    echo "    PID ${pid}  ${desc:-<未知进程>}"
    kill "$pid" 2>/dev/null || true
  done

  for _ in $(seq 1 20); do
    sleep 0.3
    if [ -z "$(port_pids "$port")" ]; then
      echo "    已释放"
      return 0
    fi
  done

  echo "    未响应，强制结束"
  for pid in $(port_pids "$port"); do kill -9 "$pid" 2>/dev/null || true; done
  sleep 0.5
  if [ -z "$(port_pids "$port")" ]; then
    echo "    已释放"
    return 0
  fi

  echo "!! 端口 ${port} 仍被占用，换一个：PORT=8020 ./run-demo.sh"
  exit 1
}

# ---------------------------------------------------------------- 环境
echo "==> Python: $($PY --version 2>&1)"
if ! $PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "!! 需要 Python 3.11 以上，当前是 $($PY --version 2>&1)"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "==> 创建虚拟环境 .venv"
  $PY -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

echo "==> 安装依赖"
pip install -q --upgrade pip >/dev/null 2>&1 || true
pip install -q -r requirements-dev.txt

free_port "$PORT"

SHOWN_HOST="$HOST"
[ "$HOST" = "0.0.0.0" ] && SHOWN_HOST="<本机IP>"

echo
echo "==> 启动： http://${SHOWN_HOST}:${PORT}/?token=demo"
echo "    (Ctrl+C 停止)"
echo
exec python -m app.demo --host "$HOST" --port "$PORT"
