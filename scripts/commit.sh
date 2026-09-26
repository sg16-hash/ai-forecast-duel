#!/usr/bin/env bash
# 把 data/ 和 reports/ 的变化提交回仓库；与其他运行冲突时自动 rebase 重试
set -euo pipefail
git config user.name  "forecast-bot"
git config user.email "forecast-bot@users.noreply.github.com"
git add -A data reports 2>/dev/null || true
if git diff --cached --quiet; then
  echo "没有变化"
  exit 0
fi
git commit -m "$1"
for i in 1 2 3; do
  git pull --rebase --autostash && git push && exit 0
  sleep $((i * 5))
done
echo "推送失败" && exit 1
