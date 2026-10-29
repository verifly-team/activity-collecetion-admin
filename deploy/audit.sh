#!/usr/bin/env bash
# 审计日志查询小工具（只读，不改任何东西）
#
#   ./deploy/audit.sh                  # 今天的汇总
#   ./deploy/audit.sh all              # 全部记录按时间列出
#   ./deploy/audit.sh zip              # 只看打包下载
#   ./deploy/audit.sh xlsx             # 只看导出 Excel
#   ./deploy/audit.sh phone            # 只看查看手机号
#   ./deploy/audit.sh ids 12           # 谁导出过第 12 号报名
#   ./deploy/audit.sh aborted          # 没下完的打包
#   ./deploy/audit.sh today 2026-10-29 # 指定日期
set -euo pipefail

CONTAINER="${CONTAINER:-verifly-export}"
CMD="${1:-summary}"

logs() {
  docker logs "$CONTAINER" 2>&1 | grep AUDIT || true
}

case "$CMD" in
  summary)
    echo "== 审计汇总（全部历史）=="
    logs | sed -E 's/.*event=([a-z_]+).*/\1/' | sort | uniq -c | sort -rn
    echo
    echo "== 最近 5 条 =="
    logs | tail -5
    ;;
  all)
    logs
    ;;
  zip)
    logs | grep "event=export_zip "
    ;;
  zipdone)
    logs | grep "event=export_zip_done"
    ;;
  xlsx)
    logs | grep "event=export_xlsx"
    ;;
  phone)
    logs | grep "event=reveal_phone"
    ;;
  aborted)
    echo "== 没下完的打包 =="
    logs | grep "event=export_zip_done" | grep "aborted=1" || echo "（没有）"
    ;;
  ids)
    ID="${2:?用法: ./deploy/audit.sh ids <报名ID>}"
    echo "== 谁动过报名 $ID =="
    logs | grep -E "ids=[0-9,]*\b${ID}\b|application_id=${ID}\b" || echo "（没有记录）"
    ;;
  today)
    DAY="${2:-$(date +%Y-%m-%d)}"
    echo "== ${DAY} 的审计 =="
    logs | grep "^${DAY}" | sed -E 's/.*event=([a-z_]+).*/\1/' | sort | uniq -c | sort -rn
    ;;
  *)
    sed -n '2,16p' "$0"
    exit 1
    ;;
esac
