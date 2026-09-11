# 这个仓库怎么用（给人看）

> 仓库：https://github.com/ABSkknnkl/a17-industry-research-agent  
> 版本：v2.1 · 2026-09-11  
> 适合：以后和你一起写代码的真人；也方便 AI 照着执行。

---

## 一、这是什么项目

一个用多个 AI 智能体自动写行业研究报告的系统。  
你只需要提一个问题，系统会自动：查数据 → 分析 → 画图 → 写正文 → 出报告。

代码在 `main` 分支上。大家改完代码合回 `main`。

---

## 二、新人怎么接入你的仓库

### 第 0 步：你（仓库主人）要准备的

在 GitHub 上把队友加进来：

1. 打开仓库 → **Settings** → **Collaborators and teams** → **Add people**
2. 输入对方 GitHub 用户名 → 邀请
3. 对方邮件里点接受

只有被邀请的人才能 `git push`。

### 第 1 步：装好电脑上的工具

需要：

- **Git**（终端里敲 `git --version` 能出来版本号）
- **GitHub 账号**（能登录 github.com）
- 可选：装 **gh** 命令行，以后开 PR 更方便

Windows 建议用 Git Bash；Mac 直接用「终端」。

### 第 2 步：把自己的代码拉下来

找仓库主人要仓库地址，然后：

```bash
git clone https://github.com/ABSkknnkl/a17-industry-research-agent.git
cd a17-industry-research-agent
```

第一次可能要登录 GitHub（输用户名密码，或用 Token）。

### 第 3 步：配置你是谁

```bash
git config user.name "你的名字"
git config user.email "你的邮箱@example.com"
```

名字随便填什么，方便辨认就行。

### 第 4 步：装上本仓库的检查钩子

在仓库目录里执行：

```bash
bash scripts/install-hooks.sh
```

以后 `git commit` 时会自动帮你挡住：  
日志文件、数据库文件、密钥、`.pytest_tmp` 这类不该进库的东西。

### 第 5 步：确认环境（建议）

后端：

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

前端：

```bash
cd frontend
npm ci
```

后端健康检查等说明见 `backend/README.md`、`docs/development/setup.md`。

### 第 6 步：你的本地目录长这样

```text
a17-industry-research-agent/     ← 你 clone 下来的仓库
├── TEAM_CONVENTION.md           ← 本说明
├── backend/                     ← Python 后端
├── frontend/                    ← Vue 前端
├── scripts/install-hooks.sh     ← 装钩子用
└── ...
```

**只在这个仓库文件夹里改代码。**  
随便在电脑别处拷一份改，以后会乱。

---

## 三、平时怎么提交代码（日常工作流）

### 1. 先更新最新代码

```bash
git switch main
git pull
```

### 2. 开一条自己的分支

```bash
git switch -c feat/你的名字-这次做什么
```

例子：

```bash
git switch -c feat/张三-修图表空数据
```

### 3. 改代码

用什么编辑器都行（VSCode、Cursor、Trae 等），只改你负责的文件。

### 4. 只把要进库的文件加进去

```bash
git status
git add backend/app/xxx.py frontend/src/yyy.vue
```

不要习惯性 `git add .`（会把垃圾也加进去）。

### 5. 提交

```bash
git commit
```

不带 `-m` 会打开编辑器，让你写提交说明。  
写一行说明就行，例如：

```
fix(backend): 张三 修好图表空数据崩溃
```

**会被直接拒的只有：**

- 空信息
- 纯数字：`1`
- 单字母：`k`

其余写得乱、用了 AI 生成的长句、姓名不对，**都能提交**。

### 6. 推到 GitHub

```bash
git push -u origin feat/你的名字-这次做什么
```

### 7. 开 Pull Request（合并请求）

在 GitHub 网页上：会弹出提示 → 点 **Compare & pull request**  
或用命令：

```bash
gh pr create
```

### 8. 等合并

- 自己或队友看一眼没问题 → 点 **Merge**（建议 Squash and merge）
- 合完 `main` 就是最新的

### 9. 合并前如果 main 又变了

```bash
git fetch origin
git rebase origin/main
# 有冲突就打开文件改完
git add 改过的文件
git rebase --continue
git push --force-with-lease
```

---

## 四、什么能进库，什么不能

| 可以进 | 不要进 |
| --- | --- |
| 你写的代码 | `logs/`、`*.log` |
| `backend/tests/` 测试源码 | `.pytest_tmp/` |
| 前端源码 | `dist/`、`node_modules/` |
| 配置文件、锁文件 | `__pycache__/`、`.venv/` |
| 重要说明文档 | `*.sqlite` 数据库文件 |
| | `.env` 密钥 |
| | `.workbuddy/` `.trae/` 等 AI 工具本地文件 |

**判断方法：**  
这个文件是你「写的」还是「跑出来的」？  
写的可以进，跑出来的不要进。

大文件（超过约 500KB）一般不要进，除非问过队友。

---

## 五、还没验证完的代码放哪

比如：AI 刚生成一大堆、你自己也不确定能不能跑。

**不要**直接塞进 `main`。

1. 开一条隔离分支：

```bash
git switch -c agent/你的名字-随便试
```

2. 可以慢慢试，**没有几天必须删的规定**。
3. 试出有用的东西后：

```bash
git switch main && git pull
git switch -c feat/你的名字-正式改动
# 从隔离分支里拷有用的文件过来
git add 具体文件
git commit
git push
# 再开 PR
```

4. **不要**把整条 `agent/xxx` 一把 merge 进 main。

---

## 六、main 分支怎么维护

| 做法 | 说明 |
| --- | --- |
| 尽量走 PR 合并 | 有个记录，出问题好找 |
| 别人在写代码时不要乱 force push | 容易把别人的东西弄丢 |
| 测试挂了别硬合 | 本地跑一下相关测试 |
| 直接 push main | **目前没有强制禁止**，能不直推就别直推 |

如果某天你们想开 GitHub 分支保护（禁止直推 main）：

```bash
bash scripts/setup-branch-protection.sh
```

脚本会先问你是不是确定（输 `yes` 才真的开）。  
**现在默认是关的。**

---

## 七、你现在提交会被拦吗

| 操作 | 结果 |
| --- | --- |
| `git commit -m "随便写"` | 可以过 |
| `git commit -m "你是一个自动化审计工具…"` | 可以过（AI prompt 也放行） |
| `git commit -m "1"` | **会拦** |
| `git add logs/x.log` | **会拦** |
| `git add backend/.env` | **会拦** |
| 测试全挂还 push | GitHub CI 会失败 |

本地想强行提交：

```bash
git commit --no-verify
```

不推荐常用。

---

## 八、每天开工前建议做这四步

```bash
git switch main
git pull
git switch -c feat/你的名字-今天干什么
# 或者切换回你昨天没做完的分支
git switch feat/你的名字-昨天那事
git fetch origin
git rebase origin/main
```

改完就 commit、push、开 PR。  
分支短命、小步提交，比攒一大包好合。

---

## 九、出问题怎么办

| 情况 | 办法 |
| --- | --- |
| 提交信息写错还没 push | `git commit --amend` 改一下 |
| 提交错了还没 push | `git reset --soft HEAD~1` 退回来重做 |
| push 被拒绝 | 先 `git pull --rebase origin main` 再 push |
| 冲突不会解 | 拉上队友一起看，别自己瞎猜 |
| 真 push 坏了 | 别 force main；开 revert 或找仓库主人 |
| 钩子太烦想关掉 | `git config --unset core.hooksPath` |

---

## 十、一页备忘

```text
开工：  git switch main && git pull
开分支：git switch -c feat/名字-简述
添加：  git add 具体文件
提交：  git commit
推送：  git push -u origin 当前分支
合并：  GitHub 上开 PR → 审一下 → Merge
实验：  用 agent/名字-试用 分支，别直接怼 main
```

---
---

# 附：给 AI / 脚本的严谨说明

> 上文是给人读的。本节给自动化、评审机器人、AI 编码代理使用。  
> 冲突时：**硬拦截以本节为准；上文写「建议」的，本节若为 MAY/SHOULD，则不构成失败。**

## A. 范围

- 远端：`ABSkknnkl/a17-industry-research-agent`
- 默认分支：`main`
- 开发分支：`feat/*` `fix/*` `docs/*` `chore/*`
- 隔离分支：`agent/*` `quarantine/*`

## B. MUST（违反则 hook 或 CI fail）

### B.1 提交信息

Reject：

- 空 header
- `^[0-9]{1,4}$`
- `^[a-zA-Z]{1,2}$`

Allow（即使格式不标准）：

- AI prompt 原文
- 非名单姓名
- 其它任意非空字符串（除上一条 Reject）

### B.2 暂存文件（pre-commit）

Reject path 匹配：

```
\.pytest_tmp/|\.workbuddy/|\.workbuddy-ai/|\.trae/|\.trae-html-share-packages/
\.claude/|\.cursor/|\.aider|node_modules/|__pycache__/|\.venv/|venv/
^logs/|^dist/|^build/|^coverage/|^htmlcov/|/artifacts/|^output/|session-log
\.(log|pids?|pid|sqlite|sqlite3|html\.zip|pyc|pyo|egg-info)$
```

Reject 敏感：

```
(^|/)(\.env|\.env\..*|.*\.pem|.*\.key|.*_rsa|.*\.p12|credentials.*|secrets?\..*)($|\.)
```

Warn only（不得 fail）：

- 文件 > 500KB
- 无 `docs/changes/`

### B.3 CI

| Job | Fail 条件 |
| --- | --- |
| commitlint | B.1 |
| backend | pytest != 0 |
| frontend | lint/build != 0 |
| hygiene | 变更路径命中 B.2 垃圾集合 |
| PR size | warning only |
| changelog | warning only |

## C. MUST NOT hard-fail

禁止因下列原因 `exit 1` 或 CI fail：

- 姓名是否在 `team.txt`
- 是否符合 `type(scope): 姓名 描述`
- 是否含 AI prompt 特征
- 文件大小
- 缺变更文档
- PR 行数
- 是否 approve 自己
- 未开保护时是否直推 / force push main

## D. 隔离分支

```
agent/<owner>-<slug>
quarantine/<owner>-<slug>
```

- 无最大存活时间
- MAY force-push / 删除
- MUST NOT 整支 merge/squash 进 `main`
- 进 main：从 `origin/main` 开干净分支 + cherry-pick/逐文件 + PR
- 同样适用 B.2

## E. 推荐提交格式（非强制）

```
<type>(<scope>): <owner> <subject>
```

## F. 分支保护

默认 off。`scripts/setup-branch-protection.sh` 交互确认后才 PUT protection。

## G. 关键路径

| 路径 | 用途 |
| --- | --- |
| `.githooks/commit-msg` | 本地信息检查 |
| `.githooks/pre-commit` | 本地文件卫生 |
| `.githooks/team.txt` | 可选名单 |
| `commitlint.config.js` | CI 信息检查 |
| `.github/workflows/ci.yml` | CI |
| `scripts/install-hooks.sh` | 安装 hooksPath |
| `scripts/setup-branch-protection.sh` | 可选保护 |
| `docs/changes/` | 可选变更文档 |
| `TEAM_CONVENTION.md` | 本文件 |

## H. Agent 附加约束

1. MUST NOT 未经确认 force-push `main` 或删除唯一真源分支。
2. MUST 将未验证改动放在 `agent/*` 或 `quarantine/*`。
3. MUST NOT 整支 merge 隔离分支进 `main`。
4. SHOULD 以最小 diff + 干净分支开 PR。
5. MUST 遵守 B.2（密钥、sqlite、测试产物）。
6. Commit message 可以非标、可含 AI 文案（见 B.1）。
7. 对远端不可逆操作（push main、删分支、开保护）SHOULD 先问用户。

## I. 版本

| 版本 | 说明 |
| --- | --- |
| v1.x | 强制规范与钩子落地 |
| v2.0 | 人话 / AI 规范拆分 |
| v2.1 | 补全人类接入仓库步骤；语气改为可独立阅读 |

## J. 人类速查

```bash
git clone https://github.com/ABSkknnkl/a17-industry-research-agent.git
cd a17-industry-research-agent
git config user.name "名字"
git config user.email "邮箱"
bash scripts/install-hooks.sh

git switch main && git pull
git switch -c feat/名字-简述
git add 文件 && git commit
git push -u origin feat/名字-简述
# GitHub 开 PR → Merge
```
