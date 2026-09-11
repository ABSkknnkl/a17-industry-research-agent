#!/usr/bin/env bash
# ============================================================================
# hygiene-check.sh —— push 之前的自检（本地跑，秒级）
#
# 检查 5 件事：
#   1. 当前分支是否太老（> 2 天）
#   2. 是否有垃圾提交信息（纯数字 / AI prompt / pre-termination backup）
#   3. 是否提交了不该进版本库的文件
#   4. 与 main 的差距（落后多少 / PR 会有多大）
#   5. 工作区是否干净
#
# 用法：bash scripts/hygiene-check.sh
# 建议：把它挂到 pre-push hook：
#   printf '#!/bin/sh\nexec bash scripts/hygiene-check.sh\n' > .husky/pre-push
# ============================================================================

MAIN_BRANCH="${MAIN_BRANCH:-main}"
MAX_BRANCH_AGE_DAYS="${MAX_BRANCH_AGE_DAYS:-2}"
WARN_PR_LINES="${WARN_PR_LINES:-400}"

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; RST=$'\033[0m'
fail=0

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "请在仓库内执行"; exit 1; }

branch=$(git rev-parse --abbrev-ref HEAD)
echo "当前分支：$branch"
echo "────────────────────────────────────────"

# ---------- 1. 分支年龄 ----------
if [ "$branch" != "$MAIN_BRANCH" ]; then
  base=$(git merge-base "$MAIN_BRANCH" HEAD)
  created=$(git show -s --format=%ct "$base")
  age=$(( ( $(date +%s) - created ) / 86400 ))
  if [ "$age" -gt "$MAX_BRANCH_AGE_DAYS" ]; then
    echo "${RED}[FAIL]${RST} 分支已存活 ${age} 天（上限 ${MAX_BRANCH_AGE_DAYS} 天）—— 请拆分或尽快合并"
    fail=1
  else
    echo "${GRN}[ OK ]${RST} 分支存活 ${age} 天"
  fi
fi

# ---------- 2. 垃圾提交信息 ----------
junk=$(git log --no-merges --pretty=format:'%h %s' "${MAIN_BRANCH}..HEAD" 2>/dev/null | \
  grep -Ei '^[0-9a-f]{7} ([0-9]{1,3}|[a-zA-Z]{1,2}|新的|测试|更新|修改|提交|备份|wip)$|你是一个|你的任务是|负责对本代码|pre-?termination' || true)
if [ -n "$junk" ]; then
  echo "${RED}[FAIL]${RST} 发现垃圾提交信息："
  echo "$junk" | sed 's/^/         /'
  echo "         修复：git rebase -i ${MAIN_BRANCH} 然后把这些提交的 pick 改成 reword"
  fail=1
else
  echo "${GRN}[ OK ]${RST} 提交信息合格"
fi

# ---------- 3. 污染文件 ----------
bad=$(git diff --name-only "$(git merge-base "$MAIN_BRANCH" HEAD)"..HEAD 2>/dev/null | \
  grep -E '^(\.pytest_tmp/|\.workbuddy/|\.workbuddy-ai/|\.trae/|\.trae-html-share-packages/|node_modules/|__pycache__/|\.venv/|logs/|data/)' || true)
if [ -n "$bad" ]; then
  echo "${RED}[FAIL]${RST} 有文件不应入库："
  echo "$bad" | head -10 | sed 's/^/         /'
  [ "$(echo "$bad" | wc -l)" -gt 10 ] && echo "         ... 还有更多"
  echo "         修复：git rm -r --cached <路径> 并把规则加进 .gitignore"
  fail=1
else
  echo "${GRN}[ OK ]${RST} 无污染文件"
fi

# ---------- 4. 与 main 的差距 ----------
behind=$(git rev-list --count "HEAD..${MAIN_BRANCH}" 2>/dev/null || echo 0)
lines=$(git diff --numstat "$(git merge-base "$MAIN_BRANCH" HEAD)"..HEAD 2>/dev/null | awk '{a+=$1; d+=$2} END {print a+d}')
lines=${lines:-0}
if [ "$behind" -gt 0 ]; then
  echo "${YEL}[WARN]${RST} 落后 ${MAIN_BRANCH} ${behind} 个提交 —— 先 git sync（rebase）再 push"
fi
if [ "$lines" -gt "$WARN_PR_LINES" ]; then
  echo "${YEL}[WARN]${RST} 本次变更 ${lines} 行（建议 ≤ ${WARN_PR_LINES} 行）—— 考虑拆 PR"
else
  echo "${GRN}[ OK ]${RST} 变更规模 ${lines} 行"
fi

# ---------- 5. 工作区 ----------
if [ -n "$(git status --porcelain)" ]; then
  echo "${YEL}[WARN]${RST} 工作区有未提交改动："
  git status --short | head -5 | sed 's/^/         /'
else
  echo "${GRN}[ OK ]${RST} 工作区干净"
fi

echo "────────────────────────────────────────"
if [ "$fail" -eq 1 ]; then
  echo "${RED}自检未通过，请先修复上述问题${RST}"
  exit 1
fi
echo "${GRN}自检通过，可以 push${RST}"
