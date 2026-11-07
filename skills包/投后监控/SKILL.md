---
name: 投后监控
description: 跟踪并分析被投企业相对计划的经营表现，读取月度或季度财务包（Excel、PDF），提取 KPI、标记预算偏差并生成摘要看板。适用于被投公司复盘、董事会材料准备和 covenant 监控。
---
## Workflow

### Step 1: Ingest Financial Package

- Accept the user's portfolio company financial package (Excel workbook, PDF, or CSV)
- Extract key financials: Revenue, EBITDA, cash balance, debt outstanding, capex, working capital
- Identify the reporting period and compare to prior period and budget/plan

### Step 2: KPI Extraction & Variance Analysis

Key metrics to track (adapt to the company's sector):

**Financial KPIs:**
- Revenue vs. budget ($ and %)
- EBITDA and EBITDA margin vs. budget
- Cash balance and net debt
- Leverage ratio (Net Debt / LTM EBITDA)
- Interest coverage ratio
- Capex vs. budget
- Free cash flow

**Operational KPIs** (ask user or infer from data):
- Customer count / revenue per customer
- Employee headcount / revenue per employee
- Backlog / pipeline
- Churn / retention rates

### Step 3: Flag & Summarize

- **Green**: Within 5% of plan
- **Yellow**: 5-15% below plan — flag for discussion
- **Red**: >15% below plan or covenant breach risk — immediate attention

Output a concise summary:
1. One-paragraph executive summary ("Company X is tracking [ahead/behind/on] plan...")
2. KPI table with actual vs. budget vs. prior period
3. Red/yellow flags with context
4. Covenant compliance status (if applicable)
5. Questions for management

### Step 4: Trend Analysis

If multiple periods are provided:
- Chart key metrics over time (revenue, EBITDA, cash)
- Identify trends — accelerating, decelerating, or stable
- Compare vs. underwriting case

## Important Notes
---

# Portfolio Monitoring

- Always ask for the budget/plan to compare against if not provided
- Don't assume sector-specific KPIs — ask what matters for this company
- If covenant levels aren't known, ask the user for the credit agreement terms
- Output should be board-ready — concise, factual, no fluff
