#!/usr/bin/env bash
# 一键跑 demo：自动建虚拟环境、装依赖、造数据、起服务
#
#   ./run-demo.sh                  # 本机预览，端口 8010
#   PORT=8011 ./run-demo.sh        # 换端口
#   HOST=0.0.0.0 ./run-demo.sh     # 允许外部访问（服务器上用）
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8010}"
HOST="${HOST:-127.0.0.1}"
PY="${PYTHON:-python3}"

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
pip install -q -r requirements.txt

if [ "$HOST" = "0.0.0.0" ] && command -v lsof >/dev/null 2>&1; then
  echo "==> 本机 IP：$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
fi

echo "==> 启动，地址： http://$( [ "$HOST" = "0.0.0.0" ] && echo '<本机IP>' || echo "$HOST" ):${PORT}/?token=demo"
echo "    (Ctrl+C 停止)"
echo
exec python -m app.demo --host "$HOST" --port "$PORT"
