# 变更：落地团队协作规范、Git 钩子、CI 门禁，并新增隔离分支约定

- 日期：2026-09-11
- 作者：张三
- 关联 PR：（待创建）
- 类型：文档 / 基础设施

## 改了什么

1. 新增 `TEAM_CONVENTION.md`（v1.1）：提交规范、上传范围、忽略规则、变更文档、分支管理、评审、冲突处理、onboarding、违规处理、周维护。
2. **v1.1 新增 §6.5 隔离分支**：明确 `agent/*`、`quarantine/*` 为未验证 / AI 产出 / 外来代码的统一入口；禁止多人共用 agent 分支；禁止整支 merge 进 main；**无存活时间限制**；仍受 hooks 卫生约束。
3. 新增 `.githooks/`：`commit-msg`（格式 + 姓名白名单 + 拦 AI prompt / 纯数字）、`pre-commit`（拦垃圾目录 / 大文件 / 敏感文件）、`team.txt`（占位名单，上线前替换为真名）。
4. 新增 `.github/`：`CODEOWNERS`、`pull_request_template.md`、`workflows/ci.yml`。
5. 新增 `commitlint.config.js`、`.gitmessage`。
6. 新增 `scripts/`：`install-hooks.sh`、`setup-branch-protection.sh`、`setup-repo.sh`、`hygiene-check.sh`。

## 为什么改

仓库此前存在：分支保护未开启、PR 长期膨胀、提交信息大量不可追溯（AI prompt 泄漏 / 纯数字）、垃圾文件被跟踪。需要一套可自动执行的协作规范，避免重蹈 `trae/agent-*` 36 天零同步的覆辙。

## 影响范围

- 不改业务代码（`backend/app/**`、`frontend/src/**`、`contracts/**`）。
- 仅新增规范 / 钩子 / CI / 脚本与文档。
- 成员本地需执行 `bash scripts/install-hooks.sh` 才会启用钩子。

## 验证方式

- 本地：`bash scripts/install-hooks.sh` 后，故意提交 `git commit -m "1"` 应被 `commit-msg` 拒绝。
- 本地：`git add .pytest_tmp/foo` 应被 `pre-commit` 拒绝。
- 服务端：PR 合并后 CI 的 commitlint / changelog job 生效。
- 分支保护：`bash scripts/setup-branch-protection.sh`（需先有 CI 成功记录）。

## 回滚方案

- 本 PR 可整支 revert。
- 钩子为本地安装，成员可 `git config --unset core.hooksPath` 立即停用。

## 遗留与风险

- `team.txt` / `CODEOWNERS` 仍为占位姓名（张三/李四/王五/赵六），**上线前必须替换为真实姓名与 GitHub 用户名**，否则钩子与 CODEOWNERS 无法真正生效。
- 分支保护脚本尚未在远端执行（`main` 当前未保护）。
- 根目录仍跟踪有 `.workbuddy*`（12）与 `eval/transcript/`（57）等产物，需另开 hygiene PR 清理。
- `agent/chart-mvp-sync` 分支内容已并入 main，可考虑删除或再打 tag 后删除。
