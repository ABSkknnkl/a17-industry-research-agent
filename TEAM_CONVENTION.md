# a17-industry-research-agent 团队协作与文档规范

> 版本 v1.1 · 更新日期 2026-09-11 · 生效日期 2026-09-09 · 适用仓库 `ABSkknnkl/a17-industry-research-agent`
> v1.1 新增：§6.5 隔离分支（未验证 / AI 产出 / 实验代码的统一入口）
> 团队规模：**4 名开发者**
> 本文件是**强制约定**，不是建议。所有机制已在 `.githooks/`、`.github/`、`commitlint.config.js` 中落地，违反会被自动拦截。

---

## 0. 团队名单与模块分工（请先填实）

| 成员 | git `user.name` 必须填 | 主责模块 | CODEOWNERS 兜底 |
| --- | --- | --- | --- |
| 成员 A | `张三` | `backend/app/agents/data_fetcher/` | 是 |
| 成员 B | `李四` | `backend/app/agents/chart_generator/`、`frontend/` | 是 |
| 成员 C | `王五` | `backend/app/agents/chapter_writer/`、`contracts/` | 是 |
| 成员 D | `赵六` | `eval/`、`backend/tests/` | 是 |

> **上线前必做**：把这张表填成真名，同步更新 `CODEOWNERS` 和 `.githooks/team.txt`。
> 提交信息里的姓名必须 **与 `team.txt` 完全一致**，否则 commit 会被钩子拒绝。

全员一次性配置（各自本机执行）：

```bash
git config user.name "张三"                       # 必须是真名，禁止 nick / 邮箱前缀
git config user.email "zhangsan@公司域名.com"      # 必须能收到 GitHub 通知
bash scripts/install-hooks.sh                     # 装钩子（见第 5.3 节）
```

---

## 1. 提交规范：每条提交必须能追溯到人

### 1.1 格式

```
<type>(<scope>): <姓名> <subject>

<body>

<footer>
```

**示例**

```
fix(backend): 张三 修复 evidence_items 空列表导致 A2 覆盖循环崩溃

当 revision 为空列表时，原实现跳过循环体直接进入赋值分支，
导致 DataInterpretReviewEdits.evidence_items 被置空。
增加空列表特判与兜底防线，补充回归测试与契约白名单。

变更文档：docs/changes/2026-09-09-张三-fix-evidence-empty-list.md
Refs #17
```

### 1.2 type 白名单

`feat` `fix` `refactor` `perf` `test` `docs` `build` `ci` `chore` `revert`

### 1.3 scope 建议

`backend` `frontend` `contracts` `eval` `docs` `agent1`…`agent5` `linter` `charts` `deps`

### 1.4 关于姓名位置的说明

推荐 `type(scope): 张三 描述`，原因：**type 在前机器可解析**（commitlint、自动生成 changelog 依赖它），姓名紧随其后在 `git log` 里一眼可见，同样满足追溯需求。

如果团队更习惯「张三：修复 xxx」这种姓名开头，把格式改成：

```
<姓名>：<type>(<scope>) <subject>
```

对应把 `commitlint.config.js` 里的 `AUTHOR_FIRST` 设为 `true`（已预留开关）。

### 1.5 硬性红线（会被钩子直接拒绝）

| 禁止 | 说明 |
| --- | --- |
| 提交信息无姓名 / 姓名不在 `team.txt` | 无法追溯责任人 |
| 纯数字、单字母（`1` `k` `新的`） | 历史不可检索 |
| 把 AI prompt 原文当提交信息 | 本仓库历史上 31 个提交犯过这个错 |
| `pre-termination backup` / `wip` / `tmp` | 会话中断请用 `git stash` |
| `git commit -m "..."` 不带正文 | 复杂改动必须写清 WHY |

### 1.6 AI Agent 提交的署名

AI 工具的提交**必须挂在使用者名下**，不能是 `traeagent` / `Copilot`：

```
feat(frontend): 李四 新增图表画廊组件

Co-authored-by: traeagent <traeagent@users.noreply.github.com>
```

`Co-authored-by` 保留（说明有 AI 参与），但 **headline 的姓名必须是人**。

---

## 2. 上传范围：只进源码和重要文档

### 2.1 必须进版本库

| 类别 | 示例 |
| --- | --- |
| 功能源码 | `backend/**/*.py`、`frontend/src/**` |
| 数据契约 | `contracts/*.schema.json`、前端 TS 类型 |
| 测试**源码** | `backend/tests/**`、前端 `*.spec.ts` |
| 构建配置 | `pyproject.toml`、`package.json`、`vite.config.ts`、锁文件 |
| 重要文档 | 需求说明、接口文档、架构决策、`docs/changes/` 变更文档、`README.md` |
| 团队约定 | 本文件、`AGENTS.md`、`CODEOWNERS`、`.githooks/` |

### 2.2 一律不进版本库

| 类别 | 具体 |
| --- | --- |
| 测试**产物** | `logs/`、`*.log`、`.pytest_tmp/`、`coverage/`、`htmlcov/` |
| 构建输出 | `dist/`、`build/`、`*.egg-info/`、`frontend/dist/` |
| 截图 / 临时报告 | `screenshots/`、`*.pdf`（评测跑出来的）、`artifacts/`、`/output/` |
| 运行时状态 | `data/checkpoints.sqlite`、`*.pid`、`*.pids` |
| 大数据/中间结果 | `eval/transcript/**` 的跑测输出、`*.jsonl` 遥测 |
| 临时压缩包 | `.trae-html-share-packages/`、`*.html.zip` |

> **判据**：这个文件是**人写的**还是**跑出来的**？人写的进，跑出来的不进。
> 唯一例外：需要作为回归基线的 fixture，放在 `eval/fixtures/` 并显式加白名单。

### 2.3 提交前自检

```bash
git status -s          # 逐条看，确认没有上面 2.2 的东西
git add <具体文件>      # 禁止 git add . / git add -A
git commit             # 不带 -m，用模板
```

> `.gitignore` 只管**未跟踪**的文件。已经进版本的必须先 `git rm --cached <路径>`（我们已做过一次 317 文件的清理）。

---

## 3. 忽略规则：AI 记忆排除，重要文档保留

### 3.1 必须排除（AI 辅助开发产生的本地记忆 / 上下文）

```
.workbuddy/            # WorkBuddy 记忆与会话状态
.workbuddy-ai/
.trae/                 # Trae 上下文
.trae-html-share-packages/
.claude/               # Claude Code 本地状态（settings.local.json 等）
.cursor/
.aider*
session-log.md         # AI 会话日志
*-session-log.md
docs/session-logs/
```

**例外白名单**（这些要进版本库）：

```
!AGENTS.md             # 团队给 AI 的统一指令，是全队共识
!CLAUDE.md             # 同上
!.claude/commands/     # 团队共享的自定义命令
```

### 3.2 必须纳入版本管理的重要文档

| 文档 | 位置 | 谁维护 |
| --- | --- | --- |
| 需求说明 | `docs/requirements/` | 需求提出人 |
| 接口文档 | `docs/api/` | 接口改动者 |
| 架构决策（ADR） | `docs/adr/` | 提案人 |
| **最终变更文档** | `docs/changes/` | **每次改代码的人**（见第 4 节） |
| 本周汇总 | `CHANGELOG.md` | 每周轮值 |

### 3.3 排错命令

```bash
git check-ignore -v <路径>     # 查某文件为什么被/不被忽略
git status --ignored -s        # 看当前忽略了哪些
git ls-files | wc -l           # 跟踪文件总数（异常增长说明漏配规则）
```

---

## 4. 最终变更文档：改完代码必须补

### 4.1 规则

- **每一个 PR 必须包含一份变更文档**，路径 `docs/changes/YYYY-MM-DD-<姓名>-<slug>.md`
- 内容必须回答三件事：**改了什么、影响范围、怎么验证**
- 同一天同一人多件事，用不同 slug 拆成多份
- 小到改一行配置也要写（可以很短，但不能没有）

### 4.2 模板（见 `docs/changes/TEMPLATE.md`）

```markdown
# 变更：<一句话概括>

- 日期：2026-09-09
- 作者：张三
- 关联 PR：#18 / Issue：#17
- 类型：功能 / 修复 / 重构 / 文档

## 改了什么
## 为什么改
## 影响范围
## 验证方式
## 回滚方案
## 遗留与风险
```

### 4.3 怎么强制

- **PR 模板**：自查清单里有勾选项，不勾 reviewer 打回（见 `.github/pull_request_template.md`）
- **CI 门禁**：`ci.yml` 的 `changelog` job 检查本次 PR 是否新增/修改了 `docs/changes/` 下文件；特殊情况下加 `no-changelog` 标签可豁免（仅限纯格式化、依赖升级）
- **评审门槛**：没有变更文档的 PR，reviewer 直接 `Request changes`

---

## 5. 落地机制（怎么保证上面四条被执行）

### 5.1 `.gitignore`

仓库根目录 `.gitignore` 已按第 2、3 节配置。追加规则见交付的 `gitignore-additions.txt`。

### 5.2 提交模板

```bash
git config commit.template .gitmessage     # 或 git config --global
```

之后 `git commit`（不带 `-m`）自动打开模板，含格式说明和姓名提示。

### 5.3 Git 钩子（本地第一道闸）

```bash
bash scripts/install-hooks.sh     # 会设置 core.hooksPath .githooks 并给可执行权限
```

| 钩子 | 拦什么 |
| --- | --- |
| `pre-commit` | ① 禁止目录/后缀（`logs/` `.pytest_tmp/` `.workbuddy/` `*.html.zip` …）② 单文件 > 500KB ③ 禁止 `.env` 类敏感文件 ④ 提醒未写变更文档。**对隔离分支同样生效**（§6.5.5） |
| `commit-msg` | ① 格式必须是 `type(scope): 姓名 描述` ② 姓名必须在 `.githooks/team.txt` ③ 拦截纯数字 / AI prompt / `wip` / `pre-termination backup` |

钩子是**本地**的，可被 `--no-verify` 绕过。所以还需要服务端兜底：

### 5.4 commitlint（服务端第二道闸）

`commitlint.config.js` 里加了 `require-author` 规则，在 CI 中对 PR 的全部提交逐条校验，绕过本地钩子的提交在这里被拦下。

### 5.5 分支保护（服务端第三道闸）

```bash
bash scripts/setup-branch-protection.sh
```

对 4 人团队的建议参数：

| 项 | 值 | 理由 |
| --- | --- | --- |
| `required_approving_review_count` | **1** | 4 人小队，1 个即可；关键目录靠 CODEOWNERS 再加一道 |
| `dismiss_stale_reviews` | true | 改完代码旧 approve 作废 |
| `require_code_owner_reviews` | true | 动到别人模块必须那人点头 |
| `require_conversation_resolution` | true | 评论没解决不让合 |
| `required_linear_history` | true | 禁止 merge commit，只走 squash/rebase |
| `allow_force_pushes` | **false** | 历史不可篡改 |
| `enforce_admins` | **true** | 管理员（仓库 owner）也不开后门 |
| `required_status_checks.strict` | true | 必须先与 main 同步 |

> 4 人团队的额外建议：给 `contracts/` 和 `.github/` 设 **2 个 approve**（在 CODEOWNERS 里指定两人）。

### 5.6 三层防护总览

```
写代码 → git add  → pre-commit 钩子（本地硬拦）
       → git commit → commit-msg 钩子（校验格式与作者）
       → git push  → CI commitlint + 变更文档门禁（服务端）
       → 开 PR     → CODEOWNERS + 1 approve + 状态检查（服务端）
       → merge     → squash 进 main
```

---

## 6. 分支管理（4 人版）

### 6.1 分支模型：Trunk-Based + 短命分支

```
main                          ← 唯一长期分支，永远可运行，受保护
 ├── feat/张三-chart-gallery   ← 已明确意图的开发分支，存活 ≤ 2 天
 ├── fix/李四-evidence-empty   ← 修复分支，存活 ≤ 1 天
 ├── docs/王五-api-contract    ← 文档分支，存活 ≤ 2 天
 └── agent/…                  ← 隔离分支，见 §6.5（可短命、可丢弃，禁止直接进 main）
```

两类分支的边界：

| | 开发分支 `feat/fix/docs/…` | 隔离分支 `agent/…` / `quarantine/…` |
| --- | --- | --- |
| 入口条件 | 你知道要做什么、改动可描述 | 未验证、AI 批量产出、试错、外部拷贝 |
| 是否必须开 PR | 是 | 否（可整支丢弃） |
| 能否进 main | 只能通过 PR + 门禁 | **只能通过从隔离分支拆出的干净 PR** |
| 合并方式 | Squash into main | **禁止整支 merge / 禁止直接 squash 进 main** |

**为什么不用 Git Flow**：4 人 + MVP 阶段 + 无并行版本维护，develop/release/hotfix 三套长期分支只会制造合并地狱。我们之前 3 条分支 36 天零同步、PR 冲突的教训就是证据。

### 6.2 分支命名（强制带姓名）

```
<type>/<姓名>-<简短slug>
```

带姓名的作用：一眼看出这是谁的分支，谁该去 rebase，谁该去删。

### 6.3 硬规则

| 规则 | 约束 |
| --- | --- |
| R1 | 分支存活 ≤ 2 天；超过 3 天必须拆分或转为 draft 说明原因 |
| R2 | 单个 PR 变更 ≤ 400 行（生成物/锁文件除外） |
| R3 | 合并前必须 `git fetch && git rebase origin/main`，**禁止 `git merge main`** |
| R4 | 合并后 24 小时内删除分支 |
| R5 | `main` 禁止直接 push，禁止 force push |
| R6 | 每人同时进行的开发分支 ≤ 2 个 |
| R7 | 未验证 / AI 产出 / 外来代码必须走隔离分支（`agent/*`、`quarantine/*`），见 §6.5；禁止其直接进 main |
| R8 | 隔离分支存活 ≤ 3 天，且禁止整支 merge 进 main |

### 6.4 合并方式：Squash and Merge

特性分支上可以有 10 个「修一下」「再改改」的提交，squash 之后 main 上只留 1 个干净提交。
**这一条对 AI 辅助开发尤其重要**——AI 在分支上制造 20 个垃圾提交无所谓，主干历史依然可读。

### 6.5 隔离分支：未验证代码的统一入口

> **动机**：不让人（或 AI）把「我不知道这能不能跑」的代码直接糊进 `main`。
> 但也**绝不允许**出现一个长期存活、人人往上堆的「公共 agent 分支」——那正是本仓库
> 历史上 `trae/agent-*` 36 天零同步、PR #1 膨胀到 1663 文件的根因。

#### 6.5.1 什么时候必须走隔离分支

| 场景 | 例子 |
| --- | --- |
| AI 会话一次性产出，未人工通读 | Trae / Claude / Cursor 批量生成的改动 |
| 外部拷贝 / 粘贴进来的代码 | 从示例仓库、文档、其他项目拷的模块 |
| 试验性重构或依赖升级 | 换 ORM、换图表库、试新框架版本 |
| 不确定能不能跑的本地半成品 | 自己写的脚本、半截实验、调试用代码 |
| 评审方案「先落盘再慢慢验」 | 比如本次要落地的 hooks / CI / 约定文件 |

**不要**为「已经想清楚、描述得出来的功能」开隔离分支——直接用 `feat/` `fix/`。

#### 6.5.2 命名与生命周期

```
agent/<姓名>-<日期或意图>
```

示例：

```
agent/张三-0912-linter-r11
agent/李四-0911-ai-chart-dump
agent/赵六-0913-dep-upgrade-try
quarantine/王五-0911-external-skill-kludge   # quarantine 与 agent 同规，语义更重：外来不明代码
```

硬规则：

| 规则 | 约束 |
| --- | --- |
| I1 | **禁止共用**一个长期 agent 分支。一人一事一分支，用完即弃 |
| I2 | 分支存活 ≤ **3 天**；到期必须选择：开 PR / 直接删除 / 群内说明延期原因 |
| I3 | 隔离分支上**可以** force push、可以 `reset --hard`、可以整支删除 |
| I4 | 隔离分支**不受** CODEOWNERS 必审约束（它们本来就不该被 review） |
| I5 | 隔离分支**同样受** `.githooks` 约束：提交信息、禁止垃圾文件 —— 未验证 ≠ 可以塞 20MB sqlite |
| I6 | 单人同时存活的隔离分支 ≤ **3** 个；超过先删旧的 |

#### 6.5.3 三种结局（必须选一个）

```
隔离分支 agent/… 
   ├─ ① 有价值 → 从它拆出干净分支 → 开 PR → 门禁 → squash 进 main → 删隔离分支
   ├─ ② 没价值 → git push origin --delete agent/…  （零成本，这就是短命分支的意义）
   └─ ③ 还要继续 → 继续推，但第 3 天仍未 PR → 群内说明 + 拆分或删除
```

**禁止**的第四种：「先都堆在 agent 分支上，以后一起验，最后一把 merge 进 main」。
那不是隔离，是把污染延迟到更难处理的时候。

#### 6.5.4 怎么从隔离分支进 main（唯一合法路径）

```bash
# 假设隔离分支是 agent/张三-0912-linter-r11，其中只有部分改动可用
git switch -c feat/张三-linter-r11 origin/main

# 逐文件/逐提交挑选，禁止 git merge agent/…
git checkout agent/张三-0912-linter-r11 -- path/to/one/file.py
# 或
git cherry-pick <sha>

# 自检：卫生、测试、变更文档
./scripts/verify.sh
# 写 docs/changes/YYYY-MM-DD-张三-linter-r11.md

git add <具体文件>
git commit      # 信息里必须写清「本人已通读/验证」
git push -u origin feat/张三-linter-r11
gh pr create    # 走正常 PR + CI + review
```

PR 描述里若改动来自隔离分支 / AI，必须写明：

```markdown
## 来源
- 自隔离分支：agent/张三-0912-linter-r11
- 是否含 AI 生成：是/否
- 人工验证：已本地跑通 X / 尚未跑（未跑通不得勾 ready）
```

#### 6.5.5 隔离分支上的卫生底线（和 main 同一套）

隔离分支**允许**提交信息随意、允许反复 force、允许脏历史，但**不允许**：

| 禁止 | 原因 |
| --- | --- |
| `.pytest_tmp/`、`logs/`、`dist/`、`*.sqlite` | 钩子直接拒绝；进历史后清理成本远高于现在拦住 |
| `.workbuddy/`、`.trae/`、`.claude/` 本地状态 | AI 记忆，不是产品代码 |
| 密钥 / `.env` | 安全红线，任何分支都不行 |
| 单次 `git add .` 塞进上百个无关文件 | 之后根本没法 cherry-pick，隔离就白隔离了 |

> 原则：**隔离的是「正确性」，不是「纪律」。**
> 脏历史可以，脏文件不行。

#### 6.5.6 与 `sandbox` 的区别（可选，4 人阶段先不用）

若将来确实需要多人联调一个不稳定的实验，可开长期 `sandbox/<主题>` 分支，但：

- **禁止**任何人直接 merge `sandbox/*` 进 main
- 只能从 sandbox **cherry-pick** 到新的干净分支再 PR
- 每周轮值可 `git push origin --delete sandbox/*` 或 `reset --hard origin/main` 清空重来

4 人 MVP 阶段：**用 `agent/*` 就够了，不要提前引入 sandbox。**

#### 6.5.7 一张图看懂

```mermaid
flowchart LR
  subgraph iso [隔离区：可糟蹋、可丢弃]
    A1["agent/张三-0912-try-x"]
    A2["agent/李四-0911-ai-dump"]
    A3["quarantine/外来代码"]
  end
  A1 -->|拆干净 + 人审 + CI| PR["feat/姓名-slug → PR"]
  A2 -->|没价值| DEL["git push --delete<br/>零成本丢弃"]
  A3 --> DEL
  PR --> M["main（受保护）"]
```

---

## 7. 代码评审

### 7.1 基本要求

| 项 | 要求 |
| --- | --- |
| 审批数 | 1 个 approve（`contracts/`、`.github/`、CI 配置为 2 个） |
| 自审 | **作者不能 approve 自己的 PR** |
| 首次响应 | 4 小时内（工作时间） |
| PR 规模 | ≤ 400 行；超出的作者自己先拆 |
| 合并人 | 由 **reviewer** 合并，不是作者自己 |

### 7.2 Reviewer 必看五项

1. **变更文档是否存在且准确**（`docs/changes/`）
2. 有没有把测试产物 / AI 记忆文件带进来
3. 数据契约改动是否同步更新了 `contracts/*.schema.json` 和前端 TS 类型
4. AI 生成的代码是否有人真正读懂（不接受「AI 写的，能跑就行」）
5. 会不会影响别人的模块（看 `影响范围` 一节）

### 7.3 评审意见分级

- 🔴 **必须改**：逻辑错误、缺变更文档、混入垃圾文件、破坏契约
- 🟡 **建议改**：命名、重复代码、可测性
- 🟢 **可选**：风格、注释

---

## 8. 冲突避免（4 人协作最容易翻车的地方）

### 8.1 每日同步仪式

```bash
# 每天开工第一件事
git switch main && git pull
git switch feat/张三-xxx
git fetch origin && git rebase origin/main     # 或 git sync 别名
```

**每天至少 rebase 一次**。冲突发现得越晚，解决成本越高——这是 4 人协作的第一铁律。

### 8.2 按模块划地盘

`CODEOWNERS` 已按第 0 节分工配置。非 owner 修改他人模块时：
1. 先在群里说一声
2. PR 必须该模块 owner approve
3. 尽量只读不改，需要改就请 owner 代劳

### 8.3 共享文件清单（改动前必须群内声明）

| 文件 | 为什么危险 |
| --- | --- |
| `contracts/*.schema.json` | 前后端耦合点，改一处两边炸 |
| `backend/pyproject.toml`、`frontend/package.json` | 依赖冲突 |
| `.github/workflows/*.yml` | 改坏全队阻塞 |
| `backend/app/core/config.py` | 配置漂移 |

### 8.4 减少冲突的具体做法

- **小步提交、小步 PR**：400 行的 PR 冲突概率远低于 4000 行
- **Draft PR 早暴露**：动手 30 分钟内开 draft PR，让别人看到你在动哪块
- **函数级拆分**：两人要改同一文件，先商量按函数/类拆成两个文件
- **Feature flag**：长任务用开关控制，代码先合进去但不启用，避免长期分支
- **禁止长期 WIP 分支**：宁可拆成 5 个小 PR，也不要开一个活两周的分支

### 8.5 冲突解决流程

```bash
git fetch origin
git rebase origin/main
# 冲突 → 逐个文件解决
git add <文件>
git rebase --continue
# 搞砸了随时退回来
git rebase --abort
```

**不要怕 `--abort`**，重来比重改冲突文件快。
遇复杂冲突（同一段逻辑两人各改各的）→ **叫上对方一起看**，不要自己猜。

---

## 9. 新人 onboarding 检查清单

新成员第一天必须完成：

- [ ] `git config user.name "真名"` / `user.email`
- [ ] `bash scripts/install-hooks.sh`
- [ ] `git config commit.template .gitmessage`
- [ ] `git config pull.rebase true`（杜绝"自己合自己"的 merge commit）
- [ ] 通读本文件，特别是第 1、2、4、6.5 节
- [ ] 认领自己在第 0 节的主责模块
- [ ] 试提交一次，确认钩子生效（故意写个 `test` 提交信息，应被拒绝）

---

## 10. 违规处理

| 违规 | 处理 |
| --- | --- |
| 提交信息无姓名 | 钩子拒绝；已推送的用 `git rebase -i` 改掉 |
| 混入垃圾文件 | 第一时间 `git rm --cached` + 补 `.gitignore` |
| 缺变更文档 | reviewer 打回，补完再审 |
| force push 到 main | 分支保护已禁；若用管理员权限强推，全队通报 |
| 分支存活超 3 天 | 作者说明原因，或强制拆分 |
| 共用长期 `agent/*` 垃圾桶分支 | 视为违规，拆分或删除；重蹈 `trae/agent-*` 覆辙 |
| 把隔离分支整支 merge 进 main | PR 直接关闭；必须按 §6.5.4 拆干净分支重来 |
| 在隔离分支提交垃圾文件（sqlite / `.pytest_tmp` / 密钥） | 钩子应已拦截；若用 `--no-verify` 绕过，全队通报 |

---

## 11. 每周维护（轮值）

```bash
# 清理已合并分支
git branch -r --merged main | grep -vE 'main|HEAD' | sed 's/origin\///' | xargs -n1 git push origin --delete

# 列出超过 3 天未动的隔离分支（需要作者处理：PR / 删除 / 延期说明）
git for-each-ref --sort=committerdate --format='%(refname:short)  %(committerdate:relative)' \
  refs/remotes/origin/agent refs/remotes/origin/quarantine

# 把 docs/changes/ 本周内容汇总进 CHANGELOG.md
```

---

## 附录 A：常用命令速查

| 场景 | 命令 |
| --- | --- |
| 开工同步 | `git switch main && git pull && git switch - && git fetch origin && git rebase origin/main` |
| 开新分支 | `git switch -c feat/张三-xxx main` |
| 提交 | `git add <具体文件> && git commit`（不带 -m） |
| 推送 | `git push -u origin feat/张三-xxx` |
| 改提交信息 | `git rebase -i origin/main`，把 `pick` 改成 `reword` |
| 撤销 add | `git restore --staged <文件>` |
| 撤销 commit（保留改动） | `git reset --soft HEAD~1` |
| 暂存手上活 | `git stash push -u -m "说明"` / `git stash pop` |
| 查责任人 | `git log -S "关键字" --oneline` / `git blame <文件>` |
| 查谁改坏了 | `git bisect start && git bisect bad && git bisect good <sha>` |
| 开隔离分支 | `git switch -c agent/张三-0912-try-x origin/main` |
| 从隔离分支挑干净提交 | `git switch -c feat/张三-xxx origin/main && git cherry-pick <sha>` |
| 丢弃隔离分支 | `git push origin --delete agent/张三-0912-try-x` + 删本地分支 |
| 列出仍存活的隔离分支 | `git branch -r \| grep -E 'origin/(agent\|quarantine)/'` |

## 附录 B：一键配置脚本

见交付目录 `scripts/install-hooks.sh`，会一次性完成：

- 设置 `core.hooksPath .githooks`
- 给钩子加可执行权限
- 设置 `commit.template .gitmessage`
- 设置 `pull.rebase true`、`push.autoSetupRemote true`
- 校验 `user.name` 是否在 `team.txt` 中（不在就提醒）
