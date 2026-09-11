#!/usr/bin/env bash
# ============================================================================
# setup-repo.sh —— 本地仓库初始化（每人执行一次）
#
# 做三件事：
#   1. git config：把 pull 默认改成 rebase（根治"自己合自己"的 merge commit）
#   2. 安装 commitlint + husky，拦截垃圾提交信息
#   3. 设置提交模板
#
# 用法：在仓库根目录执行  bash scripts/setup-repo.sh
# ============================================================================
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "错误：请在仓库根目录执行" >&2
  exit 1
fi

echo "==> [1/3] 配置 git 行为"

# 关键：pull 默认 rebase。你仓库里那个
#   "Merge branch 'agent/chart-mvp-sync' ... into agent/chart-mvp-sync"
# 就是没有这条配置造成的
git config pull.rebase true
git config rebase.autoStash true
git config rebase.autoSquash true

# 只允许 fast-forward 的 push（-f 要用 --force-with-lease）
git config push.default simple
git config push.autoSetupRemote true
git config push.followTags true

# 只 push 当前分支，避免误推
git config remote.origin.push 'HEAD'

# 合并冲突时显示共同祖先，三方 diff 更好读
git config merge.conflictStyle zdiff3

# 提交模板
if [ -f .gitmessage ]; then
  git config commit.template .gitmessage
  echo "    commit.template = .gitmessage"
fi

echo "==> [2/3] 安装 commitlint + husky"

if ! command -v node >/dev/null 2>&1; then
  echo "    未检测到 node，跳过（请先安装 Node 22，见 .nvmrc）"
else
  # 注意：某些托管终端会注入 NODE_OPTIONS 导致 npm 报错，
  # 若遇到 "Brokered host mkdir" 之类错误，改用：
  #   env -u NODE_OPTIONS npm install --save-dev ...
  npm install --save-dev @commitlint/cli @commitlint/config-conventional husky
  npx husky init
  printf '%s\n' 'npx --no-install commitlint --edit "$1"' > .husky/commit-msg
  chmod +x .husky/commit-msg
  echo "    husky commit-msg hook 已就位"
fi

echo "==> [3/3] 建议加入的 git 别名"

git config alias.st   'status -sb'
git config alias.lg   'log --oneline --graph --decorate -20'
git config alias.amend 'commit --amend --no-edit'
git config alias.sync '!git fetch origin && git rebase origin/main'
git config alias.cleanup '!git branch --merged main | grep -vE "^\*|main" | xargs -r git branch -d'

cat <<'NOTE'

完成。现在的工作循环应该是：

  git switch -c feat/17-chart-pipeline      # 从 main 切短命分支
  # ... 写代码 ...
  git add -p                                # 逐个 hunk 确认，别用 git add .
  git commit                                # 不带 -m，用模板写清楚
  git sync                                  # rebase 到最新 main
  gh pr create --fill                       # 开 PR
  # CI 绿 + 自己 Approve → Squash and merge
  git switch main && git pull && git cleanup

NOTE
