# 这个 Git 仓库怎么用（人话版）

仓库：`ABSkknnkl/a17-industry-research-agent`  
页面：https://github.com/ABSkknnkl/a17-industry-research-agent  

---

## 这个仓库是干什么的

多智能体自动写行业研报的代码。  
`main` 是主线，要尽量保持能跑。大家在自己的分支上改，改完再合进 `main`。

---

## 一、怎么加入我的仓库

### 第 1 步：有 GitHub 账号

没有的话先去 https://github.com 注册一个，记下你的用户名，比如 `xxx123`。

### 第 2 步：仓库 owner 把你加成成员

只有仓库主人（`ABSkknnkl`）能拉人：

1. 打开仓库网页
2. 点 **Settings** → **Collaborators**（或 **Manage access**）
3. 点 **Add people**
4. 输入你的 GitHub 用户名，发送邀请

你那边会在 GitHub 收到邮件，或者首页有邀请提示，点 **Accept invitation**。

权限一般选 **Write**（可读写代码）。

### 第 3 步：本机安装 Git（如果还没有）

- macOS：终端输入 `git --version`，有版本号就行；没有去装 Xcode Command Line Tools
- Windows：装 Git for Windows
- Linux：`sudo apt install git` 之类

### 第 4 步：把仓库拷到电脑

```bash
cd ~/你的代码目录
git clone https://github.com/ABSkknnkl/a17-industry-research-agent.git
cd a17-industry-research-agent
```

如果用 SSH 更顺手，先在 GitHub 上传公钥，再：

```bash
git clone git@github.com:ABSkknnkl/a17-industry-research-agent.git
```

### 第 5 步：告诉 Git 你是谁

```bash
git config user.name "张三"
git config user.email "你的邮箱@example.com"
```

邮箱用你注册 GitHub 的那个，方便对上号。

### 第 6 步：装本地小助手（钩子，可选但推荐）

```bash
bash scripts/install-hooks.sh
```

装完以后，`git commit` 会帮你挡住明显不该进库的东西（比如日志、sqlite、密钥）。  
**不会**因为你提交信息写得怪就拦你。

### 第 7 步：跑通项目（按 README）

```bash
# 后端
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 另开一个终端做前端
cd frontend
npm ci
npm run dev
```

验证：后端 `http://localhost:8000/health`，前端 `http://localhost:5173`。

---

## 二、每天怎么提交代码（照着做就行）

### 1. 先拉最新

```bash
git switch main
git pull
```

### 2. 开自己的分支

```bash
git switch -c feat/张三-修一下图表
```

名字里带你的名字，别人一看就知道是谁的。

### 3. 改代码，只添加你要的文件

```bash
git status
git add backend/app/某个文件.py
git commit
```

提交信息随便写点人能看懂的话就行。  
钩子**不会**因为「你是一个…」这种 AI 长句拦你。  
**会拦**的只有：空信息、纯数字 `1`、单字母 `k`。

### 4. 推到 GitHub

```bash
git push -u origin feat/张三-修一下图表
```

### 5. 开 Pull Request（建议）

网页上对比改动，写两句「我改了什么」，然后等合并。  
也可以自己在命令行：

```bash
gh pr create
```

### 6. 如果 main 又更新了，同步再推

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

---

## 三、哪些文件能进仓库

| 进仓库 | 别进仓库 |
| --- | --- |
| 你自己写的代码 | 测试跑出来的文件 |
| 测试**源码** `tests/` | `logs/`、`dist/`、`coverage/` |
| 配置文件、锁文件 | `.pytest_tmp/`、`__pycache__/`、`.venv/` |
| 重要文档 | `.workbuddy/`、`.trae/` 等工具记忆 |
| | 数据库 `*.sqlite` |
| | 密钥 `.env`、`.pem`、`.key` |
| | `node_modules/` |

记住一句：**人写的进，机器跑出来的不进。**

---

## 四、还不确定的代码放哪

还没验证、AI 大段生成、外面拷来的：

1. 单独开一条隔离分支，名字带自己，例如：

```bash
git switch -c agent/张三-先试一版
```

2. 这条分支**可以一直留着**，没有「几天必须删」的死规定。
3. **不要**好几个人往同一条 `agent/xxx` 里堆。
4. 确定能用了，再从 `main` 开一条干净的 `feat/...` 分支，把有用的部分挑过去，开 PR 合进 `main`。  
   不要把整条隔离分支一把 merge 进 `main`。

---

## 五、合进 main 的流程（推荐）

```text
main ──拉分支──► 你的 feat/fix 分支 ──改代码──► push ──PR──► main
```

- 测试尽量本地跑通再合。
- 大改动拆成几次，别一次糊几千行。
- 合并后分支可删可留。

---

## 六、什么时候会被拦住

| 情况 | 会不会拦 |
| --- | --- |
| 提交信息写得随意 / AI 长句 | 不拦 |
| 姓名不在名单里 | 不拦 |
| 纯数字 `1`、空信息 | **拦** |
| 提交 `logs/`、`*.sqlite`、`.env` | **拦** |
| 前后端测试挂了（CI） | **拦** |
| 直接 push `main` | 当前**不拦**（保护默认关着） |

本地想强行提交：`git commit --no-verify`。

---

## 七、分支保护要不要开（可选）

默认**不开**。想开的话，仓库 owner 在本机执行：

```bash
bash scripts/setup-branch-protection.sh
```

会先问你是不是真的要开；输入 `yes` 才真正设置。  
开了之后：合并必须走 PR、要有审核。  
不开：大家直接 push 也行，靠自觉。

---

## 八、常见问题

**Q：我 push 被拒绝？**  
先 `git pull --rebase origin main`，解决冲突后再推。不要对着 `main` 乱用 `--force`。

**Q：提交信息写错了且还没 push？**  
`git commit --amend` 改一下。

**Q：已经 push 了想改？**  
新开一个 commit 说明，或对**自己的分支** rebase 后 `--force-with-lease`。

**Q：误把日志提交进去了？**  

```bash
git rm --cached 文件路径
# 再确认 .gitignore 有对应规则，然后正常提交
```

**Q：怎么拉我进仓库？**  
让 owner 按上面「第 2 步」发邀请；你需要 GitHub 用户名。

---

## 九、命令小抄

```bash
# 拉最新
git switch main && git pull

# 开发分支
git switch -c feat/你的名-简述

# 隔离试验分支
git switch -c agent/你的名-试验

# 添加并提交
git add 文件名
git commit

# 推送
git push -u origin 当前分支名

# 同步 main 再推
git fetch origin
git rebase origin/main

# 删掉一条没用的隔离分支
git push origin --delete agent/你的名-试验
```

---

## 十、机器/脚本读的严谨条款（人类可略过）

> 下列规则供钩子、CI、AI Agent 使用。和上文冲突时，硬拦截以本节为准；其余以上文「宽松协作」为准。

### 1. 必须拦截（fail）

提交信息：

- 空 header
- `^[0-9]{1,4}$`
- `^[a-zA-Z]{1,2}$`

暂存文件路径若命中：

```
\.pytest_tmp/|\.workbuddy/|\.workbuddy-ai/|\.trae/|\.trae-html-share-packages/
\.claude/|\.cursor/|\.aider|node_modules/|__pycache__/|\.venv/
^logs/|^dist/|^build/|^coverage/|^htmlcov/|/artifacts/|^output/|session-log
\.(log|pids?|pid|sqlite|sqlite3|html\.zip|pyc|pyo|egg-info)$
```

敏感文件：

```
\.env|\.env\..*|\.pem|\.key|_rsa|\.p12|credentials|secrets?\.
```

CI：backend pytest、frontend lint/build、同上路径检查失败。

### 2. 禁止作为失败原因

- 姓名是否在 `team.txt`
- 是否符合 `type(scope): 姓名 描述`
- 是否像 AI prompt
- 文件 > 500KB
- 缺少 `docs/changes/`
- PR 行数（含 400 行）
- 直接 push `main` / force `main`（未开保护时）

### 3. 隔离分支

- 命名：`agent/<owner>-<slug>` 或 `quarantine/<owner>-<slug>`
- 无存活时间上限
- 禁止多人共用同一隔离分支
- 禁止整支 merge 进 `main`；只能从 `main` 拉干净分支 cherry-pick 后 PR

### 4. 路径约定

| 路径 | 作用 |
| --- | --- |
| `.githooks/commit-msg` | 本地提交信息 |
| `.githooks/pre-commit` | 本地文件卫生 |
| `commitlint.config.js` | CI 提交信息 |
| `.github/workflows/ci.yml` | CI |
| `scripts/install-hooks.sh` | 安装钩子 |
| `scripts/setup-branch-protection.sh` | 可选开保护 |

### 5. AI Agent 额外约束

- 未经用户确认：不得 force push `main`，不得删唯一真源
- 未验证改动进 `agent/*`，不进 `main`
- 不得整支 merge 隔离分支
- push 远端前应向用户确认

---

## 修订记录

| 日期 | 说明 |
| --- | --- |
| 2026-09-11 | 改为人话版 + 加入仓库指南 + 保留文末机器条款 |
