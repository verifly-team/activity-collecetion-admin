#!/usr/bin/env bash
# 在服务器上启动导出服务
#   ./deploy/run.sh /opt/verifly/export.env
set -euo pipefail

ENV_FILE="${1:-.env}"
IMAGE="${IMAGE:-crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com/arceus/activity-66-export:1.1.0}"
UPLOAD_DIR_HOST="${UPLOAD_DIR_HOST:-/opt/verifly/uploads}"
PORT="${PORT:-8010}"

[ -f "$ENV_FILE" ] || { echo "找不到配置文件：$ENV_FILE"; exit 1; }
[ -d "$UPLOAD_DIR_HOST" ] || { echo "附件目录不存在：$UPLOAD_DIR_HOST"; exit 1; }

docker rm -f verifly-export >/dev/null 2>&1 || true

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

sleep 3
docker ps --filter name=verifly-export --format '{{.Status}}'
curl -s "http://127.0.0.1:${PORT}/healthz" && echo
echo "页面： http://<服务器IP>:${PORT}/?token=<EXPORT_TOKEN>"
