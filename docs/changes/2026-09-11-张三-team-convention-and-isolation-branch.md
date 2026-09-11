# 变更：落地团队协作规范与隔离分支约定（宽松版）

- 日期：2026-09-11
- 作者：张三
- 关联 PR：（待创建）
- 类型：文档 / 基础设施

## 改了什么

1. 新增 `TEAM_CONVENTION.md`（v1.2 宽松版）。
2. **§6.5 隔离分支**：`agent/*`、`quarantine/*`；无存活时间限制；禁止共用与整支 merge 进 main。
3. 新增 `.githooks/`、`.github/`、`commitlint.config.js`、`.gitmessage`、相关 scripts。
4. **按反馈放宽强制项**：
   - 姓名不在 `team.txt`：放行
   - 单文件 > 500KB：只提醒
   - **AI prompt 原文当提交信息：放行**
   - 禁止直接 push main / force push / 强制 PR+approve：改为约定或可选脚本
   - PR ≤ 400 行：不强制
   - 强制变更文档、强制 AI 逐行通读：去掉

## 为什么改

降低协作摩擦；机器只拦垃圾提交与测试产物。

## 影响范围

- 不改业务代码。
- 成员需 `bash scripts/install-hooks.sh` 才启用本地钩子。

## 验证方式

- 姓名不在名单：放行。
- AI prompt 原文当提交信息：放行。
- 大文件：只警告不拒绝。
- 不跑 `setup-branch-protection.sh` 则无分支保护。
- 纯数字提交信息仍会被拒。

## 回滚方案

- PR 可 revert；`git config --unset core.hooksPath` 可停用钩子。

## 遗留与风险

- `team.txt` / CODEOWNERS 仍为占位名。
- 分支保护默认不开启。
- 根目录仍跟踪 `.workbuddy*` / `eval/transcript/`，可另开 PR 清理。
- `agent/chart-mvp-sync` 可考虑删除或再打 tag 后删。
