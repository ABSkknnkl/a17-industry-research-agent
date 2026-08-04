# ADR-001：采用能力导向的单仓库结构

- 状态：已接受
- 日期：2026-07-22

## 背景

早期骨架使用 `backend-a`、`backend-b`、`backend-c` 等人员代号作为 Python 目录。这些名称包含连字符，无法用正常 Python 导入语法使用；人员变化也会迫使架构目录变化。前后端还分别保存了公共契约说明，存在漂移风险。

## 决策

1. 保持一个仓库、一个前端应用和一个后端应用。
2. 后端按 `agents`、`workflow`、`integrations`、`infrastructure`、`reporting` 等稳定能力拆分。
3. 前端按 `reporting` 和 `review` 能力拆分。
4. 人员归属只维护在 `docs/ownership.md`，不进入包名。
5. 跨端 JSON Schema 统一放在根目录 `contracts/`。

## 后果

- Python 包可直接导入，后续人员调整不会引发目录迁移。
- 共享契约的修改位置唯一，但修改者必须同步运行契约与跨端验证。
- 各成员可以在能力目录内并行开发；公共入口、契约和架构文件仍需后端 C 审核。

