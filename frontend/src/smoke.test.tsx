import { describe, expect, it } from "vitest";

// Every routed page must at least compile and export a component. Catches broken imports and
// type-level breakage that survives `tsc` only when a module is never loaded.
const pages = import.meta.glob(
  ["./auth/*Page.tsx", "./projects/*Page.tsx", "./projects/evaluation/*Page.tsx", "./projects/ProjectLayout.tsx", "./projects/ProjectOverview.tsx"],
);

describe("page modules", () => {
  it("finds the routed pages", () => {
    expect(Object.keys(pages).length).toBeGreaterThanOrEqual(12);
  });

  for (const [path, load] of Object.entries(pages)) {
    it(`loads ${path}`, async () => {
      const mod = (await load()) as { default?: unknown };
      expect(typeof mod.default).toBe("function");
    });
  }
});
