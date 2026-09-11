#!/usr/bin/env bash
# ============================================================================
# install-hooks.sh —— 新成员一键配置（每人执行一次）
#
# 做四件事：
#   1. 启用 .githooks（pre-commit + commit-msg）
#   2. 设置提交模板 .gitmessage
#   3. 设置 pull.rebase=true（杜绝"自己合自己"的 merge commit）
#   4. 校验 user.name 是否在团队名单里
#
# 用法：在仓库根目录执行  bash scripts/install-hooks.sh
# ============================================================================
set -uo pipefail

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; RST=$'\033[0m'

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "错误：请在仓库根目录执行" >&2
  exit 1
fi

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT" || exit 1

echo "==> [1/4] 启用本地钩子"
if [ ! -d .githooks ]; then
  echo "    找不到 .githooks 目录，跳过"
else
  chmod +x .githooks/pre-commit .githooks/commit-msg 2>/dev/null
  git config core.hooksPath .githooks
  echo "    core.hooksPath = .githooks"
  for h in pre-commit commit-msg; do
    [ -x ".githooks/$h" ] && echo "    ✓ $h 已启用" || echo "    ✗ $h 不可执行，请检查"
  done
fi

echo "==> [2/4] 设置提交模板"
if [ -f .gitmessage ]; then
  git config commit.template .gitmessage
  echo "    commit.template = .gitmessage"
else
  echo "    找不到 .gitmessage，跳过"
fi

echo "==> [3/4] 设置 git 行为"
git config pull.rebase true
git config rebase.autoStash true
git config rebase.autoSquash true
git config push.autoSetupRemote true
git config push.followTags true
git config merge.conflictStyle zdiff3
echo "    pull.rebase = true（pull 默认变基，不再产生 merge commit）"
echo "    merge.conflictStyle = zdiff3（冲突时显示共同祖先，更好读）"

echo "==> [4/4] 校验身份"
NAME=$(git config user.name || true)
EMAIL=$(git config user.email || true)

if [ -z "$NAME" ]; then
  printf "    ${RED}✗ 未设置 user.name${RST}\n      执行：git config user.name \"你的真名\"\n"
else
  echo "    user.name  = $NAME"
  if [ -f .githooks/team.txt ] && ! grep -qxF "$NAME" .githooks/team.txt; then
    printf "    ${YEL}! 「$NAME」不在团队名单 .githooks/team.txt 中，提交会被拒绝${RST}\n"
    printf "      当前名单：%s\n" "$(tr '\n' ' ' < .githooks/team.txt)"
  else
    echo "    ✓ 已在团队名单中"
  fi
fi

if [ -z "$EMAIL" ]; then
  printf "    ${RED}✗ 未设置 user.email${RST}\n      执行：git config user.email \"你的公司邮箱\"\n"
else
  echo "    user.email = $EMAIL"
fi

cat <<'NOTE'

────────────────────────────────────────
配置完成。验证钩子是否生效（应被拒绝）：

    git commit --allow-empty -m "test"

预期输出：✗ 提交被拒绝 · 纯数字提交信息没有信息量

另建议在 ~/.gitconfig 里加别名：

    git config --global alias.sync '!git fetch origin && git rebase origin/main'
    git config --global alias.lg 'log --oneline --graph --decorate -20'

详细约定见 TEAM_CONVENTION.md
NOTE
