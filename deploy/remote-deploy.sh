#!/usr/bin/env bash
# 在阿里云服务器上执行：拉新镜像 → 重启容器 → 健康检查 → 失败自动回滚
#
#   /verifly/activity-export/remote-deploy.sh <完整镜像地址:tag>
#
# 由 GitHub Actions 上传并调用，也可以手动跑。
set -euo pipefail

IMAGE="${1:?用法: remote-deploy.sh <镜像地址:tag>}"
CONTAINER="${CONTAINER:-verifly-export}"
PORT="${PORT:-8010}"
ENV_FILE="${ENV_FILE:-/verifly/activity-export/export.env}"
UPLOAD_DIR_HOST="${UPLOAD_DIR_HOST:-/verifly/activity/uploads}"
AUDIT_DIR_HOST="${AUDIT_DIR_HOST:-/verifly/activity-export/audit}"
STATE_FILE="/verifly/activity-export/.last-image"
LOG_FILE="/verifly/activity-export/deploy.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"; }

# ---------------------------------------------------------------- 上次的镜像（用于回滚）
PREV=""
[ -f "$STATE_FILE" ] && PREV="$(cat "$STATE_FILE")"

log "开始部署：$IMAGE"
[ -n "$PREV" ] && log "当前版本：$PREV"

[ -f "$ENV_FILE" ] || { log "❌ 找不到 $ENV_FILE"; exit 1; }
mkdir -p "$AUDIT_DIR_HOST"

# ---------------------------------------------------------------- 拉镜像
log "拉取镜像…"
if ! docker pull "$IMAGE" >>"$LOG_FILE" 2>&1; then
  log "❌ 拉取失败，保持现状不动"
  exit 1
fi

# ---------------------------------------------------------------- 启动
start_container() {
  local img="$1"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d \
    --name "$CONTAINER" \
    --restart unless-stopped \
    --network host \
    --env-file "$ENV_FILE" \
    -e UPLOAD_DIR=/data/uploads \
    -e AUDIT_LOG_PATH=/data/audit/audit.jsonl \
    -v "$UPLOAD_DIR_HOST:/data/uploads:ro" \
    -v "$AUDIT_DIR_HOST:/data/audit" \
    --cpus=1 --memory=512m \
    --log-opt max-size=20m --log-opt max-file=3 \
    "$img" \
    uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1 >>"$LOG_FILE" 2>&1
}

health_check() {
  for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

log "启动容器…"
start_container "$IMAGE"

if health_check; then
  echo "$IMAGE" > "$STATE_FILE"
  log "✅ 部署成功：$IMAGE"
  docker ps --filter "name=$CONTAINER" --format '   {{.Image}}  {{.Status}}' | tee -a "$LOG_FILE"
  exit 0
fi

# ---------------------------------------------------------------- 回滚
log "❌ 健康检查失败，开始回滚"
docker logs --tail 30 "$CONTAINER" >>"$LOG_FILE" 2>&1 || true

if [ -z "$PREV" ]; then
  log "没有上一个版本可回滚，容器保持停止状态，请人工介入"
  exit 1
fi

log "回滚到：$PREV"
start_container "$PREV"
if health_check; then
  log "⚠️  已回滚到 $PREV（新版本 $IMAGE 有问题，请检查）"
  exit 1
else
  log "❌ 回滚也失败了，需要人工处理：docker logs $CONTAINER"
  exit 1
fi
