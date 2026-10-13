import { describe, expect, it } from "vitest";
import { approxCost, formatCost, formatTokens } from "./cost";

describe("formatCost", () => {
  it("never shows false precision", () => {
    expect(formatCost(null)).toBe("—");
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.004)).toBe("<$0.01");
    expect(formatCost(1.234)).toBe("$1.23");
    expect(formatCost(1234.5)).toBe("$1,235");
  });

  it("does not double up the approximation marker", () => {
    expect(approxCost(0.004)).toBe("<$0.01");
    expect(approxCost(2)).toBe("~$2.00");
    expect(approxCost(0)).toBe("$0");
    expect(approxCost(null)).toBe("—");
  });
});

describe("formatTokens", () => {
  it("abbreviates thousands and millions", () => {
    expect(formatTokens(880)).toBe("880");
    expect(formatTokens(3521)).toBe("3.5K");
    expect(formatTokens(12_400)).toBe("12K");
    expect(formatTokens(2_000_500)).toBe("2.0M");
  });
});
