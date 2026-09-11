#!/usr/bin/env bash
# ============================================================================
# setup-branch-protection.sh
# 为 main 开启分支保护 —— 这是整套流程里最重要的一步（装刹车）
#
# 前置：
#   1. 已安装 gh 并登录：  gh auth login
#   2. CI 至少成功跑过一次（否则 status check 名字在 GitHub 里不存在）
#
# 用法：
#   chmod +x scripts/setup-branch-protection.sh
#   OWNER=ABSkknnkl REPO=a17-industry-research-agent ./scripts/setup-branch-protection.sh
# ============================================================================
set -euo pipefail

OWNER="${OWNER:-ABSkknnkl}"
REPO="${REPO:-a17-industry-research-agent}"
BRANCH="${BRANCH:-main}"

echo "==> 为 ${OWNER}/${REPO} 的 ${BRANCH} 开启分支保护"

gh api -X PUT "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Commit Message",
      "Backend (py3.12)",
      "Frontend (node22)",
      "Repo Hygiene",
      "Change Doc"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "require_last_push_approval": false
  },
  "required_conversation_resolution": true,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "lock_branch": false
}
JSON

echo "==> 完成。验证："
gh api "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
  --jq '{protected: .enabled // true, enforce_admins: .enforce_admins.enabled, reviews: .required_pull_request_reviews.required_approving_review_count, checks: [.required_status_checks.contexts[].context]}'

cat <<'NOTE'

4 人团队配置说明：
  strict: true                → 分支必须先与 main 同步才允许合并（防止冲突进主干）
  enforce_admins: true        → 管理员（仓库 owner）也同样受限，不留后门
  required_linear_history    → 禁止 merge commit，只能 squash / rebase
  allow_force_pushes: false   → 禁止 force push，历史不可篡改
  allow_deletions: false      → 禁止误删 main

  required_approving_review_count = 1
      4 人小队 1 个 approve 即可，避免互相阻塞。
      GitHub 本身禁止作者 approve 自己的 PR，所以不会出现"自己审自己"。
      contracts/ 与 .github/ 这类关键目录靠 CODEOWNERS 里写两个 owner 实现"双签"。

  如果后面发现评审质量不够，把 count 提到 2 即可：
      gh api -X PATCH repos/OWNER/REPO/branches/main/protection \
        -F required_pull_request_reviews.required_approving_review_count=2
NOTE

如果 GitHub 提示 "Required status check ... not found"，说明该 check 还没跑过，
先把 CI 文件推进 main 跑一次，再执行本脚本。
NOTE
