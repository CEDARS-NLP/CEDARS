/** Dollar amounts for LLM spend are tiny and approximate; never show false precision. */
export function formatCost(usd: number | null | undefined): string {
  if (usd == null) return "—";
  if (usd === 0) return "$0";
  if (usd < 0.01) return "<$0.01";
  return `$${usd < 10 ? usd.toFixed(2) : Math.round(usd).toLocaleString()}`;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

/** "~$1.20" for an estimate; "<$0.01" already reads as approximate, so no tilde. */
export function approxCost(usd: number | null | undefined): string {
  const text = formatCost(usd);
  return text.startsWith("$") && text !== "$0" ? `~${text}` : text;
}
