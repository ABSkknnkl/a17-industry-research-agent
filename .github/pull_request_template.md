## 做了什么

<!-- 一句话说清这次改动达成了什么效果。 -->

## 为什么做

<!-- 可选：关联 Issue。 -->

## 变更文档（可选）

<!-- 建议写，不强制。路径 docs/changes/YYYY-MM-DD-<姓名>-<slug>.md -->

- 变更文档路径：`docs/changes/`______________________

## 影响范围

- [ ] `backend/`
- [ ] `frontend/`
- [ ] `contracts/`
- [ ] `eval/`
- [ ] `docs/`
- [ ] 无外部影响

## 提交前自查（建议，不强制）

- [ ] 提交信息大致为 `type(scope): 姓名 描述`
- [ ] 已从 main 最新处 rebase
- [ ] 本地 `pytest` 与 `npm run build` 通过
- [ ] **没有**混入测试产物：`logs/` `.pytest_tmp/` `*.log` `coverage/` `dist/`
- [ ] **没有**混入 AI 本地记忆：`.workbuddy/` `.trae/` `.claude/`
- [ ] 若含 AI 生成代码：尽量自己通读过一遍（不强制）

## 验证方式

```
pytest backend/tests/xxx/test_xxx.py -q
npm run build
```

## 回滚方案

---

### Reviewer 检查项（建议）

- [ ] 无垃圾文件混入
- [ ] 数据契约已同步（如涉及）
