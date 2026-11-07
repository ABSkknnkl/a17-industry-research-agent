---
name: 外汇
description: 提供基于实时外汇 API 的货币汇率查询与金额转换能力的标准 Vercel AI SDK Tool 集合
---

# currency-skills

这是一个面向 AI Agent 的「货币转换技能」。它封装了一组 **Vercel AI SDK Tools**，用于：

- 查询某个基准货币（如 USD、EUR、CNY）的最新汇率表
- 将指定金额从一种货币转换为另一种货币（如 100 USD → CNY）

所有能力都通过 `src/ai/tools/currency.ts` 暴露，导出对象为 `currencyTools`。

---

## When to use（何时调用这个技能）

当用户出现以下需求时，Agent 应优先考虑使用本技能：

- 明确询问「汇率」「兑换」「换算」「多少人民币/美元/欧元」等问题  
  - 例如：「帮我查下 1 USD 等于多少 CNY？」  
  - 例如：「我有 100 欧元，换成人民币大概多少？」  
- 需要基于**实时外汇数据**做判断或计算，而不是拍脑袋估算
- 需要生成带有精确数值的报告、邮件、报价单、旅行预算等内容

如果只是**泛泛聊经济形势或历史汇率走势**，不需要精确数字，则不必调用该技能。

---

## Capabilities（能力）

当前技能暴露了两类标准 Tool（均为 Vercel AI SDK 规范）：

1. **`rateLookup`**
   - **用途**：根据基准货币获取一整张汇率表  
   - **Tool 描述**：`"根据基准货币查询最新外汇汇率表（Frankfurter API）"`  
   - **参数 (`parameters`)**：
     - `baseCurrency: string` — 三位货币代码（ISO 4217），例如 `USD`、`EUR`、`CNY`
   - **返回**（简化说明）：
     - `base: string` — 实际基准货币代码
     - `date?: string` — 汇率日期（由 API 返回）
     - `currencies: { code: string; rate: number }[]` — 按代码排序的汇率列表

2. **`convertCurrency`**
   - **用途**：将指定金额从一种货币换算为另一种货币  
   - **Tool 描述**：`"根据实时汇率将金额从一种货币转换为另一种货币"`  
   - **参数 (`parameters`)**：
     - `from: string` — 源货币代码，如 `USD`
     - `to: string` — 目标货币代码，如 `CNY`
     - `amount: number` — 需要转换的金额（必须为正数）
   - **返回**（简化说明）：
     - `from: string`
     - `to: string`
     - `amount: number`
     - `rate: { fromRate: number; toRate: number }`
     - `result: number` — 换算后的金额
     - `summary: string` — 便于复述的人类可读描述（如 `"100 USD ≈ 712.34 CNY"`）

---

## Trigger Rules（触发规则）

Agent 在满足以下任一条件时，**应该主动考虑调用本技能**：

1. 用户问题中同时出现「金额 + 货币代码」以及「换算/兑换/等于多少」等表达  
2. 用户提到「最新汇率」「实时汇率」「今天的汇率」等时间敏感表述  
3. 需要输出需要精确到至少 2 位小数的金额对比、预算或报价

**不应触发本技能的情况：**

- 用户只是在讨论宏观经济、汇率趋势，不要求具体数值  
- 用户显式说明「不用太精确」「大概估算一下就行」

---

## Instructions（调用与使用指引）

1. **优先选择合适的 Tool：**
   - 如果用户需要的是「一整张多个货币的汇率表」，使用 `rateLookup`
   - 如果用户只关心「A 货币 → B 货币的单次转换」，优先使用 `convertCurrency`

2. **参数构造：**
   - 所有货币代码均使用三位大写字母（如 `USD`、`CNY`），如果用户给的是小写或带符号（如 `$`），先在自然语言中判断，再映射成标准代码
   - 对金额进行基本 sanity check：如果用户没有给出金额，不要盲目调用 `convertCurrency`

3. **错误处理：**
   - 如果后端返回「不支持的货币代码」，在回复中要清楚说明是哪一个代码无效，并建议用户改用常见币种
   - 网络错误或第三方 API 故障时，向用户解释「当前汇率服务不可用」，而不是给出凭空猜测的数字

4. **结果呈现：**
   - `convertCurrency` 返回的 `summary` 字段可以直接用于自然语言回答的骨架，在此基础上补充语气和解释
   - 对汇率、金额等数值建议保留 2–4 位小数，并在回答中注明货币代码，避免歧义

---

## Examples（Few-shot 示例）

- 用户：`帮我查一下今天 1 USD 等于多少 CNY？`  
  - Agent：调用 `convertCurrency`，参数 `{ from: "USD", to: "CNY", amount: 1 }`，再根据返回的 `summary` 组织回答。

- 用户：`我有 500 EUR，大概能换多少美元？`  
  - Agent：调用 `convertCurrency`，参数 `{ from: "EUR", to: "USD", amount: 500 }`。

- 用户：`给我一张以 CNY 为基准的常见货币汇率表。`  
  - Agent：调用 `rateLookup`，参数 `{ baseCurrency: "CNY" }`，然后以表格或列表形式呈现部分结果。

