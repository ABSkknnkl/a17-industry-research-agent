# currency-skills

基于 Vercel AI SDK 的标准「货币汇率 / 转换」技能包。

提供一组工具（Tools），让你的 AI Agent 可以：

- 查询指定基准货币的最新汇率表（`rateLookup`）
- 将金额从一种货币转换为另一种货币（`convertCurrency`）

实现代码位于 `src/ai/tools/currency.ts`，并通过 `currencyTools` 导出。

---

## 安装与构建

```bash
npm install
npm run build
```

构建后，编译产物输出在 `dist/`，技能入口文件为：

- `dist/ai/tools/currency.js`

---

## 测试

项目内置了 Vitest 测试用例，覆盖了两个核心工具：

- `rateLookup`：验证能否正确返回 USD 基准的汇率列表
- `convertCurrency`：验证 `100 USD -> EUR` 转换是否返回合理结果

运行测试：

```bash
npm test
```

---

## 在 Vercel AI SDK 中使用

在你的应用代码中（例如一个 API 路由或服务端模块），先引入工具集合：

```ts
import { currencyTools } from "./ai/tools/currency";
```

然后在 Vercel AI SDK 的调用中挂载：

```ts
import { streamText } from "ai";
import { openai } from "@ai-sdk/openai";

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = await streamText({
    model: openai("gpt-4.1-mini"),
    messages,
    tools: currencyTools,
  });

  return result.toAIStreamResponse();
}
```

模型即可根据对话内容，自主调用：

- `rateLookup`：获取汇率表
- `convertCurrency`：执行具体金额的货币转换

---

## 与 Agent Skill 结构

本仓库同时提供：

- `SKILL.md`：面向 AI 的技能说明文档（何时触发、能力、示例等）
- `skill.json`：技能的机器可读元数据（入口文件、tools schema、权限声明等）

这两者方便你在更大的 Agent 编排系统中，将本仓库作为一个可复用的「货币技能模块」集成。

