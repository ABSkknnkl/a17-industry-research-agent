import { describe, it, expect } from "vitest";
import { currencyTools } from "./currency";

describe("currencyTools", () => {
  it(
    "rateLookup: should return rates for base currency",
    async () => {
      const result = await currencyTools.rateLookup.execute({
        baseCurrency: "USD",
      });

      expect(result).toBeDefined();
      expect(result.base).toBe("USD");
      expect(Array.isArray(result.currencies)).toBe(true);
      expect(result.currencies.length).toBeGreaterThan(0);

      // 至少包含自身 USD
      const hasUSD = result.currencies.some((c) => c.code === "USD");
      expect(hasUSD).toBe(true);
    },
    // Vitest v4: timeout 通过 this.setTimeout 或 test timeout 配置即可
  );

  it("convertCurrency: should convert amount between currencies", async () => {
    const result = await currencyTools.convertCurrency.execute({
      from: "USD",
      to: "EUR",
      amount: 100,
    });

    expect(result).toBeDefined();
    expect(result.from).toBe("USD");
    expect(result.to).toBe("EUR");
    expect(result.amount).toBe(100);
    expect(typeof result.result).toBe("number");
    expect(result.result).toBeGreaterThan(0);
    expect(result.summary).toContain("USD");
    expect(result.summary).toContain("EUR");
  });
});

