## 做了什么

<!-- 一句话说清这次改动。不是"改了哪些文件"，是"达成了什么效果"。 -->

## 为什么做

<!-- 关联 Issue：Closes #17 / Refs #17。没有 Issue 的 PR 请先开 Issue。 -->

## 最终变更文档 ⚠️ 必填

<!-- 团队约定第 4 条：每次改完代码必须补写或更新变更文档。
     路径 docs/changes/YYYY-MM-DD-<姓名>-<slug>.md，模板见 docs/changes/TEMPLATE.md -->

- 变更文档路径：`docs/changes/`______________________
- [ ] 已写「改了什么 / 影响范围 / 验证方式」三要素
- [ ] 不需要变更文档（仅限纯格式化、依赖升级）→ 请加 `no-changelog` 标签并说明：______

## 影响范围

- [ ] `backend/`
- [ ] `frontend/`
- [ ] `contracts/`（数据契约变更 → 必须同步 `contracts/*.schema.json` 和前端 TS 类型，且需 2 人 approve）
- [ ] `eval/`
- [ ] `docs/`
- [ ] 无外部影响

## 提交前自查

- [ ] 提交信息格式 `type(scope): 姓名 描述`，姓名在 `.githooks/team.txt` 中
- [ ] 单个 PR 变更 ≤ 400 行（超出请拆分或说明原因）
- [ ] 已从 main 最新处 rebase：`git fetch origin && git rebase origin/main`
- [ ] 本地 `pytest` 与 `npm run build` 通过
- [ ] **没有**混入测试产物：`logs/` `.pytest_tmp/` `*.log` `coverage/` `dist/` 截图 `*.pdf`
- [ ] **没有**混入 AI 本地记忆：`.workbuddy/` `.workbuddy-ai/` `.trae/` `.claude/` `session-log.md`
- [ ] 本次改动若由 AI 生成：已人工完整 review，理解每一行

## 验证方式

<!-- 评审人怎么复现验证？贴命令与预期结果。 -->

```
pytest backend/tests/xxx/test_xxx.py -q
npm run build
```

| 场景 | 预期 | 实测 |
| --- | --- | --- |
| | | |

## 回滚方案

<!-- 合进去之后出问题怎么退？ -->

---

### Reviewer 检查项

- [ ] 变更文档与实际改动一致
- [ ] 无垃圾文件混入
- [ ] 数据契约已同步（如涉及）
- [ ] AI 生成代码已被人工读懂
