# 同花顺问财 SkillHub 行业研究智能体

本项目将数据获取、数据解读、图表生成、章节写作和报告融合五个阶段串联起来，支持按阶段审核、查看证据和下载报告。前端使用 Vue 3，后端使用 FastAPI 和自研状态机。

## 快速开始

在项目目录下安装 Python 3.11+、Node.js 22–26 和 npm 10+ 后：

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium  # 生成 PDF 时需要
cd frontend && npm ci && cd ..
```

首次配置时可复制 `.env.example` 为 `.env`，再填写所需凭证。**已有 `.env` 时不要覆盖。**也可在前端设置页面配置模型和问财接口。更详细的操作及配置优先级见 [SETUP.md](SETUP.md)。

```bash
./start_system.sh
```

脚本会强制释放 8000、5173 端口，请先确认端口没有其他服务。前端默认 <http://localhost:5173>，后端 API 为 <http://localhost:8000/api/v1>，接口文档为 <http://localhost:8000/docs>。

当前后端未配置统一身份认证，设置接口会返回配置中的密钥；默认服务不适合直接暴露到公网或不受信任网络。

## 当前验证与接手

截至2026-11-02，当前审计仍未通过正式研报交付。最新问题排序、修复状态、回归记录与接手说明见[唯一审计总文档](output/report-integrity-validation-20261101/verification_report.md)。旧主题专用运行/续跑脚本和失效演示脚本已清理；新建任务保留通用`scripts/run_real_pipeline.py`，自动运行/续跑保留`scripts/run_pipeline_auto.py`。

## 使用与限制

创建任务时可选择人工审核阶段；各阶段产出和引用应结合原始数据审核。系统使用 `record_id` 传递证据，但不能保证每条结论正确或每次数据完整。图表和报告可能因数据、模型或导出失败而降级。

融合报告直接编辑后，旧 PDF 和质检结论作废，完整视图可重新生成 Markdown/HTML 供预览；重新融合并质检后才能定稿并生成新 PDF。重新融合可能重新生成正文，需要核对之前的直接修改。

产业链图主图采用确定性 SVG，附加 HTML 截图和 AI 配图是可选路径；`CHAIN_ENGINE=evidence_v2` 可在创建任务时选择共享研究包，未设置时使用 legacy 路径。

## 验证

```bash
.venv/bin/python -m pytest                 # 默认排除 live 测试
cd frontend && npm run verify && npm run build
npm run test:e2e                          # 使用本机 Chrome
```

最新验证以[审计总文档](output/report-integrity-validation-20261101/verification_report.md)为准；[当前版本说明](docs/当前版本说明.md)保留功能与历史合并边界。默认测试不执行付费服务，真实运行与离线验证分别记录。

## 目录

- `backend/`：API、状态机、存储和智能体适配。
- `frontend/`：Vue 工作台、审核、预览和下载。
- `agents_core/`：五个智能体、产业链研究共享包和共享策略。
- `data/runs/`：任务状态和产物；`output/`：部分独立运行产物。
- `docs/`：五行业调优方案、当前版本说明和系统测试报告。
- `../skills包/`：工作区内的技能资源。
- `../项目全景技术深度解析.md`：系统的全景架构白皮书与工程深度解析。

- [五行业投研报告专项调优方案](docs/superpowers/plans/2026-11-06-research-report-delivery.md)
- [当前版本说明](docs/当前版本说明.md)
- [系统测试报告](docs/06_系统测试报告.md)
