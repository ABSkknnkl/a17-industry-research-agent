# AGENTS.md — 本仓库 AI Agent 必读

> 适用：Claude Code / Codex / Trae / Cursor 等所有在本仓库工作的 AI
> 仓库：`ABSkknnkl/a17-industry-research-agent`
> 依据：2026-09-11 团队对话定稿（宽松协作 + 最小硬拦截）
> 人类可读说明：见 `TEAM_CONVENTION.md` 上半部分；本文件是机器/Agent 协议。

---

## 0. 最高原则

1. **先问再动不可逆操作**：push 远端、删分支、改 `main`、加协作者、开分支保护，未经用户确认不要做。
2. **未验证代码进隔离分支**，不要直接怼 `main`。
3. **硬拦截清单之外全部放行**；不要擅自加严（例如拦 AI prompt、拦姓名、拦大文件、强制 PR）。
4. **不要提交**测试产物、密钥、AI 本地记忆目录。
5. 改业务代码前先搜索现有实现；能改就不要新建平行模块。

---

## 1. 角色分工（系统侧）

五阶段流水线（与 Agent 编号无关，禁止混淆）：

| Stage | 职责 | 是否调 LLM |
| --- | --- | --- |
| `data_fetch` | 意图 → Skill 路由 → 拉证据 | 是（拆解/语义） |
| `data_interpret` | 固定公式算术 + LLM 解读 | 是 |
| `chart_generate` | 规则出图，无数据不画 | 否 |
| `chapter_write` | 7 章 21 节，数值必须挂 evidence_ids | 是 |
| `report_fusion` | 确定性融合 MD/HTML/PDF | 否 |

**红线**：

- 禁止让 LLM 自己算财务比率并当作 fact 写入。
- 禁止伪造 evidence_id / 空证据当成功。
- 禁止在生产路径回退 Mock（Mock 仅测试进程）。

---

## 2. Git：硬拦截（违反必须失败）

### 2.1 提交信息

MUST reject：

- 空 header
- `^[0-9]{1,4}$`
- `^[a-zA-Z]{1,2}$`

MUST allow（禁止因此 fail）：

- AI prompt 原文
- 不在 `team.txt` 的姓名
- 任意非上述模式的描述

### 2.2 暂存文件

MUST reject path 命中：

```
\.pytest_tmp/|\.workbuddy/|\.workbuddy-ai/|\.trae/|\.trae-html-share-packages/
\.claude/|\.cursor/|\.aider|node_modules/|__pycache__/|\.venv/|venv/
^logs/|^dist/|^build/|^coverage/|^htmlcov/|/artifacts/|^output/|session-log
\.(log|pids?|pid|sqlite|sqlite3|html\.zip|pyc|pyo|egg-info)$
```

MUST reject 敏感文件：

```
\.env|\.env\..*|\.pem|\.key|_rsa|\.p12|credentials|secrets?\.
```

### 2.3 CI

MUST fail：backend pytest、frontend lint/build、上述 forbidden paths、commitlint 对 §2.1 的硬拦。

MUST NOT fail：PR 行数、缺 `docs/changes/`、提交格式、姓名。

---

## 3. Git：禁止作为失败原因

下列情况 Agent 与 CI **禁止** hard-fail：

- 提交姓名是否在名单
- 是否符合 `type(scope): 姓名 描述`
- 是否像 AI prompt / AI 长句
- 单文件 > 500KB
- 缺少变更文档
- PR 行数（含 400 行阈值）
- 未开保护时直接 push `main` / force `main`

---

## 4. 分支协议

### 4.1 开发分支

```
feat/<owner>-<slug>
fix/<owner>-<slug>
docs/<owner>-<slug>
```

从 `origin/main` 拉出；合并前建议 rebase。

### 4.2 隔离分支（未验证 / AI 产出 / 外部拷贝）

```
agent/<owner>-<slug>
quarantine/<owner>-<slug>
```

规则：

| MUST | MUST NOT |
| --- | --- |
| 一人一事一分支 | 多人共用同一条 `agent/*` |
| 无存活时间上限，可长期保留 | 因「超期」擅自删除他人分支 |
| 进 main 只能：从 main 开干净分支 → cherry-pick/选文件 → PR | 整支 merge/squash 隔离分支进 main |
| 同样适用 §2.2 文件黑名单 | 以「未验证」为由提交 sqlite/密钥 |

单人同时存活隔离分支建议 ≤ 5（非 hard-fail）。

### 4.3 main

- 默认：**不强制**禁止直接 push（保护可选）。
- Agent：**未经用户确认** MUST NOT force push `main` 或删除远端唯一真源。
- 用户说「合到 main / 提交到 main」时，按其指令执行；能先分支再 merge 更稳妥。

### 4.4 远端可见操作

下列操作前 MUST 向用户确认（不可逆或对外可见）：

- `git push`（尤其 `main`）
- 删除远端分支 / tag
- `gh pr merge`
- `gh api` 改协作者、分支保护、仓库设置
- force push

---

## 5. 拉人进仓库（协作者）

仅仓库 Admin 可操作。当前 Admin：`ABSkknnkl`。

### 5.1 网页

`Settings → Collaborators → Add people → 输入 GitHub 用户名 → 权限 Write`

### 5.2 命令行

```bash
gh api -X PUT \
  repos/ABSkknnkl/a17-industry-research-agent/collaborators/<github_username> \
  -f permission=push
```

`push` = Write。对方需 Accept 邀请。

**Agent MUST NOT** 在未给出明确用户名、未获确认时调用该 API。  
**Agent MUST NOT** 猜测或使用「最近联系人」当邀请对象。

### 5.3 对方接入后本机配置

```bash
git clone https://github.com/ABSkknnkl/a17-industry-research-agent.git
cd a17-industry-research-agent
git config user.name "他的名字"
git config user.email "他的邮箱"
bash scripts/install-hooks.sh
```

---

## 6. 代码契约（改代码时遵守）

### 6.1 依赖方向

```
api → workflow → agents → integration protocols
integrations / infrastructure 实现协议，不反向依赖 api
frontend 只依赖公开 API / contracts JSON Schema
```

### 6.2 契约源

- 跨端唯一契约：`contracts/schemas/`
- 运行时模型：`backend/app/schemas/`
- 前后端字段 snake_case；枚举不可只改一端

### 6.3 外部调用

- 经 `ToolGateway` / `ModelGateway`；超时、有限重试、结构化错误
- SkillHub 优先；`WEB_SEARCH` 仅兜底；`eastmoney.com` 已在 allowlist
- 禁止绕过 gateway 直连网络

### 6.4 隐私

- 日志与 `RuntimeEvent`：不写 token、prompt 原文、可疑模型输出、用户敏感原文
- 证据需可溯源（source / time / unit / grade），查不到就报缺口

### 6.5 测试

- 单测默认 mock：`LLM_USE_MOCK` / `SKILLHUB_USE_MOCK` = True（conftest 已设）
- 真实链路仅 `test_real_full_chain` / `real_runner`，需显式配置
- 改核心逻辑先补/改对应 `backend/tests/**`

---

## 7. 目录速查

| 路径 | 用途 |
| --- | --- |
| `backend/app/` | FastAPI + 五阶段 Agent |
| `backend/tests/` | 确定性单测 |
| `eval/` | 评测（快照/代打/scorers） |
| `contracts/` | 跨端 JSON Schema |
| `frontend/` | Vue 审核工作台 |
| `.githooks/` | 本地钩子 |
| `scripts/install-hooks.sh` | 安装 `core.hooksPath` |
| `TEAM_CONVENTION.md` | 人类说明 + 协议摘要 |
| `AGENTS.md` | 本文件，Agent 协议 |

---

## 8. 典型工作流（Agent 应照此执行）

### 8.1 用户说「改一个小功能」

1. `git switch main && git pull`
2. `git switch -c feat/<owner>-<slug>`
3. 搜索/阅读相关代码后修改
4. 跑相关测试
5. `git add <具体文件>`（禁止无差别 `git add .`）
6. commit（格式尽量 `type(scope): 姓名 描述`，但不强制）
7. 若需上远端：先确认再 push
8. 用户要求则开 PR / 合 main

### 8.2 用户说「AI 生成了一大坨，先放着」

1. `git switch -c agent/<owner>-<slug> origin/main`
2. 提交产物（仍避开 §2.2 黑名单）
3. 告知用户：分支名、如何验证、如何拆干净 PR
4. **不要**自动 merge 进 main

### 8.3 用户说「把 XXX 拉进仓库」

1. 确认对方 **GitHub 用户名**（必须用户给出，禁止猜测）
2. 确认权限默认 `push`
3. 执行 §5.2 或指示用户网页操作
4. 复述：已发邀请、对方需 Accept、如何 clone

### 8.4 用户给了外部数据源（如东财研报）

1. 检查是否已在 `WEB_SEARCH` allowlist
2. 已在：说明走兜底路径，不改代码
3. 未在：解释与 SkillHub 主路径的差异，确认后再改 allowlist
4. 禁止新增 HTML 爬虫硬塞进 Agent1（除非用户明确要求并知情）

---

## 9. 提交与历史

- 优先小 diff；大改拆分
- 不要改写已推送历史（`push --force` 仅限自己的未合并分支且需确认）
- 历史中已存在的脏 message / 泄漏：默认不改写，需要时用户明确要求再处理
- 归档 tag：`archive/*` 仅作回滚保险，删除需用户确认

---

## 10. 文档写法

- 给人：大白话、少术语、可直接操作
- 给 AI：路径 + MUST/MUST NOT + 命令
- 不要生成「打算/以后会」的空头承诺文档
- 不要创建未要求的重复 README

---

## 11. 当前已知状态（2026-09-11）

- `main` 最新人话规范：`TEAM_CONVENTION.md`
- 第二分支示例：`docs/team-readme`（已合入 main）
- 分支保护：**默认关闭**
- 协作者：仅 `ABSkknnkl`（待用户给出用户名后再拉人）
- `team.txt` 占位名可用；真名可选
- AI prompt 作 commit message：**允许**
- 钩子：需各成员本机 `scripts/install-hooks.sh` 才生效

---

## 12. 自检清单（Agent 提交前）

- [ ] 未误加 `.pytest_tmp` / logs / sqlite / .env / node_modules
- [ ] 未把隔离分支整支 merge 进 main
- [ ] 未在无确认时 force push / 删远端 / 改协作权限
- [ ] 改了契约则前后端一起考虑
- [ ] 核心逻辑有对应测试
- [ ] 提交信息至少非空、非纯数字、非单字母
