#!/usr/bin/env bash
# ============================================================================
# setup-branch-protection.sh
# 【可选】为 main 开启分支保护 —— 默认不自动执行
#
# 按团队要求：禁止直接 push main、强制 PR/审查等 **不做硬性强制**，
# 只提供本脚本供你们在需要时手动打开。不跑本脚本，相关规则仅是约定提醒。
#
# 用法（手动、可选）：
#   OWNER=ABSkknnkl REPO=a17-industry-research-agent ./scripts/setup-branch-protection.sh
#   # 关闭保护：
#   gh api -X DELETE "repos/${OWNER:-ABSkknnkl}/${REPO:-a17-industry-research-agent}/branches/main/protection"
# ============================================================================
set -euo pipefail

OWNER="${OWNER:-ABSkknnkl}"
REPO="${REPO:-a17-industry-research-agent}"
BRANCH="${BRANCH:-main}"

cat <<'NOTE'
==> 提醒：分支保护是可选的（当前默认不强制）

团队约定里「禁止直接 push main」「必须 PR」「必须 N 个 approve」等
现在只作 **约定提醒**，不靠 GitHub 强制。

若你们某天决定打开保护，再运行本脚本。打开后 main 将：
  - 必须走 PR 才能合并
  - 禁止 force push
  - 需要 ≥1 approve（contracts/ 等靠 CODEOWNERS）
  - CI 状态检查必须通过

NOTE

read -r -p "是否现在真的开启 main 分支保护？(yes/NO) " ans
if [ "${ans}" != "yes" ]; then
  echo "==> 已跳过。main 仍可直接 push（按当前宽松策略）。"
  exit 0
fi

echo "==> 为 ${OWNER}/${REPO} 的 ${BRANCH} 开启分支保护"

gh api -X PUT "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "Commit Message",
      "Backend (py3.12)",
      "Frontend (node22)",
      "Repo Hygiene"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1,
    "require_last_push_approval": false
  },
  "required_conversation_resolution": false,
  "required_linear_history": false,
  "allow_force_pushes": true,
  "allow_deletions": false,
  "block_creations": false,
  "lock_branch": false
}
JSON

echo "==> 已开启（宽松版保护）。验证："
gh api "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
  --jq '{enabled: .enabled // true, reviews: .required_pull_request_reviews.required_approving_review_count, allow_force: .allow_force_pushes.enabled, checks: [.required_status_checks.contexts[].context]}'

cat <<'NOTE'

宽松版说明：
  required_approving_review_count = 1  → 至少 1 个 approve
  allow_force_pushes: true             → 仍允许 force（按你的要求不强制禁止）
  enforce_admins: false                → 管理员也可绕
  Change Doc 不在必检列表            → 变更文档只提醒

若要更严，把各字段改严格后再跑一次；若要完全关闭：
  gh api -X DELETE repos/OWNER/REPO/branches/main/protection
NOTE
