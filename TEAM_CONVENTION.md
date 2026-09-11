# a17-industry-research-agent Git 使用与维护说明

> 本文件分两部分：**上半给人看（大白话）**，**下半给 AI / 脚本读（严谨规范）**。
> 仓库：`ABSkknnkl/a17-industry-research-agent`
> 版本：v2.0 · 2026-09-11

---

# 上半：给人看（怎么提交、怎么维护）

## 这仓库在干什么

用多智能体自动写行业研报。主干 `main` 保持能跑；大家从 `main` 拉分支改代码，再合回去。

## 你第一次要做的三件事

```bash
git config user.name "张三"
git config user.email "你的邮箱@example.com"
bash scripts/install-hooks.sh
```

装钩子以后，`git commit` 会自动帮你挡「明显不该进库」的东西。

## 怎么提交（照这个走就行）

### 1. 动手前先拉最新

```bash
git switch main
git pull
git switch -c feat/张三-你的任务简写
```

分支名建议带上你的名字，方便找人。

### 2. 改代码时只 add 你要进的文件

```bash
git status
git add 某个文件.py 另一个文件.ts
```

少用 `git add .`，容易把垃圾一并带进去。

### 3. 写提交信息

**建议**格式（不强制，写好找历史方便）：

```
fix(backend): 张三 修好图表空数据崩溃
```

**会被直接拒掉的只有：**

- 空的提交信息
- 纯数字：`1` `123`
- 单字母：`k` `ok`

其余（姓名不对、格式随便、AI 生成的长句、乱七八糟描述）**都能提交**，钩子最多提醒一下。

复杂改动建议正文里写清楚：改了什么、为什么、怎么验证。

### 4. 推分支、开 PR

```bash
git push -u origin feat/张三-xxx
gh pr create
```

合并前如果 main 又有更新，先同步再推：

```bash
git fetch origin
git rebase origin/main
```

### 5. 合并后

分支可以删；也可以留着当记录。没有硬性时间限制。

---

## 什么能进库，什么不能

| 进库 | 不进库 |
| --- | --- |
| 你自己写的代码 | 测试跑出来的文件 |
| 测试源码（`tests/`） | `logs/`、`coverage/`、`dist/` |
| 项目配置、锁文件 | `.pytest_tmp/`、`__pycache__/`、`.venv/` |
| 重要文档 | `.workbuddy/`、`.trae/` 等工具本地状态 |
| | 数据库文件 `*.sqlite` |
| | 密钥 `.env`、`.pem`、`.key` |
| | `node_modules/` |

**一句话：人写的、跑起来要用的，进；跑出来、机器生成的，不进。**

钩子和 CI 会拦：测试垃圾、日志、sqlite、密钥。  
**不会**拦：大文件（只提醒）、没写变更文档（只提醒）、提交信息丑（只提醒）。

---

## 不确定的代码放哪（隔离分支）

还没验证、AI 批量生成的、外面抄来的，**别直接怼 main**。

1. 开一条自己的隔离分支（名字带你的名）：

```
agent/张三-随便试什么
```

2. 可以长期留，也可以随时删，**没有过期时间**。
3. **不要**好几个人往同一条 `agent/xxx` 里堆东西。
4. 有用的部分，挑干净后再开一条 `feat/...` 分支，走正常 PR 进 main。  
   **不要**把整条隔离分支一把 merge 进 main。

---

## main 怎么维护

- 尽量从 PR 进 main，别自己直接猛推一堆。
- 直接 push main / force push：**当前没强制禁止**（GitHub 分支保护默认关），靠自觉。
- 想开保护时执行：`bash scripts/setup-branch-protection.sh`（要手输 `yes`）。
- 测试挂了别硬合：本地跑一下再推。

---

## 日常习惯（建议，不强制）

- 一次一个小改动，别攒超大包。
- 改完尽量自己点一点或跑下相关测试。
- 隔离分支用完能删就删。
- 合并过的分支删了省心。

---

## 你现在会不会被拦

| 情况 | 结果 |
| --- | --- |
| `git commit -m "随便写点啥"` | 能过 |
| `git commit -m "你是一个自动化…"`（AI prompt） | 能过 |
| `git commit -m "1"` | **拦** |
| `git add logs/x.log` 然后 commit | **拦** |
| `git add backend/.env` 然后 commit | **拦** |
| 没装钩子时直接 push | 钩子不生效；CI 仍可能拦垃圾路径和测试失败 |

本地想强行：`git commit --no-verify`。

---
---

# 下半：给 AI 看（严谨规范）

> 以下为**机器可执行规范**。上半文的「建议」在本节若写明 `MUST NOT` / `MUST`，则以本节为准。
> 当前产品策略：**宽松协作**。硬拦截面刻意最小化。

## A. 范围与角色

- 仓库根：`ABSkknnkl/a17-industry-research-agent`
- 默认分支：`main`
- 分支类型：
  - 开发分支：`feat/*` `fix/*` `docs/*` `chore/*` 等，意图明确的功能/修复
  - 隔离分支：`agent/*` `quarantine/*`，未验证/AI 产出/外部拷贝

## B. 硬拦截（MUST 违反则失败）

### B.1 提交信息（`.githooks/commit-msg`，CI `commitlint` 同步）

MUST reject：

- 空 header
- header 匹配 `^[0-9]{1,4}$`
- header 匹配 `^[a-zA-Z]{1,2}$`

MUST allow（即使不符合推荐格式）：

- AI prompt 原文
- 非白名单姓名
- 任意非上述空/数字/双字母的字符串

### B.2 暂存区（`.githooks/pre-commit`）

MUST reject 若 staged path 匹配：

```
\.pytest_tmp/|\.workbuddy/|\.workbuddy-ai/|\.trae/|\.trae-html-share-packages/
\.claude/|\.cursor/|\.aider|node_modules/|__pycache__/|\.venv/|venv/
^logs/|^dist/|^build/|^coverage/|^htmlcov/|/artifacts/|^output/|session-log
\.(log|pids?|pid|sqlite|sqlite3|html\.zip|pyc|pyo|egg-info)$
```

MUST reject 若 staged path 匹配敏感模式：

```
(^|/)(\.env|\.env\..*|.*\.pem|.*\.key|.*_rsa|.*\.p12|credentials.*|secrets?\..*)($|\.)
```

MUST NOT reject：

- 单文件 > 500KB（仅 warning）
- 缺少 `docs/changes/`（仅 warning）

### B.3 CI（`.github/workflows/ci.yml`）

| Job | fail 条件 |
| --- | --- |
| commitlint | 同 B.1 |
| backend | pytest 非 0 |
| frontend | lint/build 非 0 |
| hygiene | 变更文件路径命中 B.2 垃圾路径集合 |
| PR size | 仅 warning |
| changelog | 仅 warning |

## C. 不强制（MUST NOT hard-fail）

以下**禁止**作为 CI fail 或 hook `exit 1` 的原因：

- 提交姓名是否在 `.githooks/team.txt`
- 是否符合 `type(scope): 姓名 描述`
- 是否包含 AI prompt 语料特征
- 文件大小阈值（>500KB）
- 缺少变更文档
- PR diff 行数（含 400 行阈值）
- 作者是否 approve 自己
- 是否直接 push `main`（未开启分支保护时）
- 是否 force push `main`（未开启分支保护时）

## D. 隔离分支协议（供 agent / 自动化遵守）

### D.1 命名

```
agent/<owner>-<slug>
quarantine/<owner>-<slug>
```

`owner`：git `user.name` 或可识别短名。  
禁止多个 owner 共享同一隔离分支。

### D.2 生命周期

- 无最大存活天数。
- MAY 长期保留。
- MAY force-push / `reset --hard` / 删除。
- MUST NOT 将隔离分支整支 merge/squash 到 `main`。
- 进 `main` 的唯一路径：从 `origin/main` 开干净分支，cherry-pick 或逐文件选取后走 PR。

### D.3 卫生

隔离分支同样适用 B.2。  
「未验证」不豁免「禁止提交 sqlite / 密钥 / 测试产物」。

### D.4 建议容量

单人同时存活隔离分支建议 ≤ 5（非硬失败）。

## E. 推荐但非强制的提交格式

```
<type>(<scope>): <owner> <subject>
```

`type ∈ {feat,fix,refactor,perf,test,docs,build,ci,chore,revert}`  
`scope ∈ {backend,frontend,contracts,eval,docs,agent1..5,linter,charts,deps,release}`（开放，不 enum 强制）

仅用于人读 changelog；**不得**因格式失败阻塞 commit/CI（除 B.1 硬拦项）。

## F. 分支保护（可选）

默认：**关闭**。  
开启脚本：`scripts/setup-branch-protection.sh`（交互确认 `yes`）。  
开启前脚本 MUST 明示「此为可选」；未确认 MUST 退出 0 且不调用 API 写保护。

## G. 文件布局约定（路径，供工具解析）

| 路径 | 用途 |
| --- | --- |
| `.githooks/commit-msg` | 本地提交信息检查 |
| `.githooks/pre-commit` | 本地暂存区卫生 |
| `.githooks/team.txt` | 可选名单（提醒用） |
| `commitlint.config.js` | 服务端提交信息检查 |
| `.github/workflows/ci.yml` | CI |
| `.github/CODEOWNERS` | 模块归属（保护开启时才强） |
| `.github/pull_request_template.md` | PR 模板（可选填写） |
| `scripts/install-hooks.sh` | 安装 `core.hooksPath` |
| `scripts/setup-branch-protection.sh` | 可选开启保护 |
| `scripts/hygiene-check.sh` | 卫生自查 |
| `docs/changes/` | 可选变更说明 |
| `TEAM_CONVENTION.md` | 本文件 |

## H. 变更文档 schema（可选）

若创建 `docs/changes/YYYY-MM-DD-<owner>-<slug>.md`，建议字段：

```yaml
title: string
date: date
owner: string
type: enum(feature|fix|refactor|docs|infra|other)
summary: string
# 可选
changes: string
impact: string
verify: string
rollback: string
```

无文件不得失败。

## I. AI Agent 行为约束（写给自动化）

1. Agent MUST NOT 在未获用户确认时 force-push `main` 或删除远端唯一真源分支。
2. Agent MUST 将未验证/试验性改动置于 `agent/*` 或 `quarantine/*`。
3. Agent MUST NOT 把隔离分支整支 merge 进 `main`。
4. Agent SHOULD 从干净分支 + 最小 diff 产出 PR。
5. Agent MUST 遵守 B.2 文件黑名单；不得以「宽松」为由提交密钥或 sqlite。
6. Agent 生成的 commit message 允许非标准格式与 AI 文案（见 C）；但 SHOULD 尽量可读。
7. Agent SHOULD 在 push 远端前向用户确认（不可逆或对外可见操作）。

## J. 版本

| 版本 | 说明 |
| --- | --- |
| v1.0 | 初版强制规范 |
| v1.1 | 增加隔离分支、取消隔离分支时限 |
| v1.2 | 放宽姓名/大文件/分支保护/PR 行数/变更文档 |
| v2.0 | 文档拆分为「人类大白话 + AI 严谨规范」；AI prompt 提交信息放行 |

---

## 附录：人类速查命令

```bash
# 同步
git switch main && git pull

# 开发分支
git switch -c feat/你的名-简述

# 隔离分支
git switch -c agent/你的名-试验名

# 提交（不带 -m 可打开模板）
git add 文件 && git commit

# 推送
git push -u origin 当前分支名

# 丢弃隔离分支
git push origin --delete agent/你的名-试验名

# 查看钩子是否安装
git config core.hooksPath
```
