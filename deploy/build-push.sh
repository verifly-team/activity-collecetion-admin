#!/usr/bin/env bash
# 构建并推送导出服务镜像
#   ./deploy/build-push.sh 1.1.0
set -euo pipefail
cd "$(dirname "$0")/.."

REGISTRY="${REGISTRY:-crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com}"
NAMESPACE="${NAMESPACE:-arceus}"
IMAGE="${IMAGE:-activity-66-export}"
TAG="${1:-$(date +%Y%m%d-%H%M)}"
PLATFORM="${PLATFORM:-linux/amd64}"
FULL="$REGISTRY/$NAMESPACE/$IMAGE"

echo "==> 构建 $FULL:$TAG  (platform=$PLATFORM)"
DOCKER_BUILDKIT=0 docker build --platform "$PLATFORM" -t "$FULL:$TAG" -t "$FULL:latest" .

echo "==> 推送"
docker push "$FULL:$TAG"
docker push "$FULL:latest"

echo "==> 完成 $FULL:$TAG"
