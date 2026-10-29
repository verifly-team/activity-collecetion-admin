#!/usr/bin/env bash
# 本地完整复刻 GitHub Actions 的每一步 —— 推之前跑这个，避免浪费 CI 额度。
#
#   ./deploy/ci-local.sh          # 只跑测试三步（约 1 分钟）
#   ./deploy/ci-local.sh --docker # 额外验证 docker build（约 2 分钟）
#
# 与 CI 的差异：这脚本用的是「纯净检出」（git archive），
# 不会用到你本地 .venv 里碰巧装过的包。
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_DOCKER=0
[ "${1:-}" = "--docker" ] && WITH_DOCKER=1

WORK="$(mktemp -d)"
VENV="$WORK/venv"
SRC="$WORK/src"
trap 'rm -rf "$WORK"' EXIT

PY="${PYTHON:-python3}"
if command -v python3.12 >/dev/null 2>&1; then
  PY="python3.12"   # 与 CI 一致
fi

echo "==> 1/5 纯净检出（只有 git 跟踪的文件）"
mkdir -p "$SRC"
git archive HEAD | tar -x -C "$SRC"
echo "    $(find "$SRC" -type f | wc -l | tr -d ' ') 个文件 → $SRC"

echo "==> 2/5 新建虚拟环境（$($PY --version 2>&1)）"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true

echo "==> 3/5 安装依赖（requirements-dev.txt）"
"$VENV/bin/pip" install -q -r "$SRC/requirements-dev.txt"

cd "$SRC"
echo "==> 4/5 代码风格"
"$VENV/bin/ruff" check app tests
"$VENV/bin/ruff" format --check app tests

echo "==> 5/5 单元测试（pytest -q，与 CI 完全相同）"
"$VENV/bin/pytest" -q

if [ "$WITH_DOCKER" = "1" ]; then
  echo "==> 附加：docker build"
  docker build -t ci-local-check "$SRC"
  echo "    镜像构建成功：ci-local-check"
fi

echo
echo "✅ 全部通过，可以放心 push"
