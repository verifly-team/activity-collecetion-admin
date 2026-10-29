#!/usr/bin/env bash
# 在服务器上启动导出服务
#   ./deploy/run.sh /opt/verifly/export.env
#   PORT=8020 ./deploy/run.sh /opt/verifly/export.env
#   NO_KILL=1 ./deploy/run.sh ...     # 端口被占用时不自动清理
set -euo pipefail

ENV_FILE="${1:-.env}"
IMAGE="${IMAGE:-crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com/arceus/activity-66-export:1.3.0}"
UPLOAD_DIR_HOST="${UPLOAD_DIR_HOST:-/opt/verifly/uploads}"
PORT="${PORT:-8010}"
NO_KILL="${NO_KILL:-0}"

[ -f "$ENV_FILE" ] || { echo "找不到配置文件：$ENV_FILE"; exit 1; }
[ -d "$UPLOAD_DIR_HOST" ] || { echo "附件目录不存在：$UPLOAD_DIR_HOST"; exit 1; }

# ---------------------------------------------------------------- 清理旧容器与端口
docker rm -f verifly-export >/dev/null 2>&1 || true

port_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:${PORT}" 2>/dev/null || true
  else
    ss -lntp 2>/dev/null | awk -v p=":${PORT}\$" '$4 ~ p {print $NF}' \
      | sed -E 's/.*pid=([0-9]+).*/\1/' | sort -u | grep -v '^$' || true
  fi
}

pids=$(port_pids)
if [ -n "$pids" ]; then
  echo "==> 端口 ${PORT} 被占用："
  for pid in $pids; do
    echo "    PID ${pid}  $(ps -p "$pid" -o command= 2>/dev/null | cut -c1-90 || echo '<未知进程>')"
  done
  if [ "$NO_KILL" = "1" ]; then
    echo "!! NO_KILL=1，不自动清理，退出"
    exit 1
  fi
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  for _ in $(seq 1 20); do
    sleep 0.3
    [ -z "$(port_pids)" ] && break
  done
  for pid in $(port_pids); do kill -9 "$pid" 2>/dev/null || true; done
  sleep 0.5
  if [ -z "$(port_pids)" ]; then
    echo "    已释放"
  else
    echo "!! 仍被占用，换端口：PORT=8020 ./deploy/run.sh $ENV_FILE"
    exit 1
  fi
fi

# ---------------------------------------------------------------- 启动
docker run -d \
  --name verifly-export \
  --restart unless-stopped \
  --network host \
  --env-file "$ENV_FILE" \
  -e UPLOAD_DIR=/data/uploads \
  -v "$UPLOAD_DIR_HOST:/data/uploads:ro" \
  --cpus=1 --memory=512m \
  --log-opt max-size=20m --log-opt max-file=3 \
  "$IMAGE" \
  uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1

sleep 4
docker ps --filter name=verifly-export --format '{{.Status}}'
echo "--- 自检 ---"
if curl -sf "http://127.0.0.1:${PORT}/healthz"; then
  echo
else
  echo "!! /healthz 不通，看日志： docker logs --tail 30 verifly-export"
  exit 1
fi
echo "页面： http://<服务器IP>:${PORT}/?token=<EXPORT_TOKEN>"
