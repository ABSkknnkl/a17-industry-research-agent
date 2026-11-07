import { z } from "zod";

const API_BASE = "https://api.frankfurter.dev/v1";

const CurrencyCodeSchema = z
  .string()
  .min(3)
  .max(3)
  .transform((s) => s.toUpperCase())
  .describe("三位货币代码（ISO 4217），例如 USD、EUR、CNY");

const PositiveAmountSchema = z
  .number()
  .positive()
  .describe("需要转换的金额，必须为正数");

type CurrencyCode = z.infer<typeof CurrencyCodeSchema>;

interface FetchRatesResponse {
  base: string;
  date?: string;
  rates: Record<string, number>;
  amount?: number;
}

async function fetchRates(base: CurrencyCode) {
  const res = await fetch(`${API_BASE}/latest?base=${base}`);
  if (!res.ok) {
    throw new Error(`Rate API error: ${res.status}`);
  }
  const data = (await res.json()) as FetchRatesResponse;
  const baseRate = data.amount ?? 1;

  const currencies = [
    { code: data.base, rate: baseRate },
    ...Object.entries(data.rates ?? {}).map(([code, rate]) => ({
      code,
      rate: rate as number,
    })),
  ];

  return {
    base: data.base,
    date: data.date,
    currencies,
  };
}

function convert(amount: number, fromRate: number, toRate: number) {
  return (amount / fromRate) * toRate;
}

export const rateLookupTool = {
  description: "根据基准货币查询最新外汇汇率表（Frankfurter API）",
  parameters: z.object({
    baseCurrency: CurrencyCodeSchema,
  }),
  // Vercel AI SDK 兼容的 Tool 形态：execute(args) => Promise<unknown>
  execute: async ({ baseCurrency }: { baseCurrency: CurrencyCode }) => {
    const { base, date, currencies } = await fetchRates(baseCurrency);

    const sorted = [...currencies].sort((a, b) => a.code.localeCompare(b.code));

    return {
      base,
      date,
      currencies: sorted,
    };
  },
} as const;

export const convertCurrencyTool = {
  description: "根据实时汇率将金额从一种货币转换为另一种货币",
  parameters: z.object({
    from: CurrencyCodeSchema.describe("源货币代码，例如 USD"),
    to: CurrencyCodeSchema.describe("目标货币代码，例如 CNY"),
    amount: PositiveAmountSchema,
  }),
  execute: async ({
    from,
    to,
    amount,
  }: {
    from: CurrencyCode;
    to: CurrencyCode;
    amount: number;
  }) => {
    const { currencies } = await fetchRates(from);

    const fromCur = currencies.find((c) => c.code === from);
    const toCur = currencies.find((c) => c.code === to);

    if (!fromCur) {
      throw new Error(`Unsupported source currency: ${from}`);
    }
    if (!toCur) {
      throw new Error(`Unsupported target currency: ${to}`);
    }

    const result = convert(amount, fromCur.rate, toCur.rate);

    return {
      from,
      to,
      amount,
      rate: {
        fromRate: fromCur.rate,
        toRate: toCur.rate,
      },
      result,
      summary: `${amount} ${from} ≈ ${result.toLocaleString(undefined, {
        maximumFractionDigits: 4,
      })} ${to}`,
    };
  },
} as const;

export const currencyTools = {
  rateLookup: rateLookupTool,
  convertCurrency: convertCurrencyTool,
};

