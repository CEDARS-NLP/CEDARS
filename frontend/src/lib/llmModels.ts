/**
 * LLM provider and model catalog shared by the project create page and project
 * settings.
 *
 * The Bedrock entries are the part that earns its keep. Bedrock model IDs are
 * long, versioned, and — for every current Anthropic model — only reachable
 * through a *cross-region inference profile*, which means the ID must carry a
 * region prefix (`us.`). Typing the bare on-demand ID
 * (`anthropic.claude-sonnet-5`) is accepted by the form and then fails at call
 * time with an opaque ValidationException, which is exactly how the deployed
 * project ended up misconfigured. Offering the known-good IDs as presets makes
 * that mistake unreachable for the common case.
 *
 * These were taken from `aws bedrock list-inference-profiles` (ACTIVE only).
 * They are account- and region-dependent, so the free-text escape hatch stays.
 */

export interface ProviderOption {
  value: string;
  label: string;
}

export const PROVIDERS: ProviderOption[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "vllm", label: "vLLM" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "bedrock", label: "AWS Bedrock" },
];

export interface ModelPreset {
  /** Exact model ID sent to the provider. */
  id: string;
  /** Human label for the dropdown. */
  label: string;
  /** One-line "when would I pick this" hint. */
  hint: string;
}

/**
 * Curated presets per provider. A provider absent from this map (vLLM, Ollama)
 * has no meaningful defaults — the model depends on what the user has pulled or
 * served — so it gets a plain text field.
 */
export const MODEL_PRESETS: Record<string, ModelPreset[]> = {
  bedrock: [
    {
      id: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
      label: "Claude Haiku 4.5",
      hint: "Fastest and cheapest — good default for scanning large note sets",
    },
    {
      id: "us.anthropic.claude-sonnet-5",
      label: "Claude Sonnet 5",
      hint: "Balanced accuracy and cost — recommended for most projects",
    },
    {
      id: "us.anthropic.claude-opus-5",
      label: "Claude Opus 5",
      hint: "Highest accuracy on subtle clinical criteria, slowest and priciest",
    },
    {
      id: "us.anthropic.claude-sonnet-4-6",
      label: "Claude Sonnet 4.6",
      hint: "Previous generation — use if you need to match an earlier run",
    },
  ],
  openai: [
    { id: "gpt-4o-mini", label: "GPT-4o mini", hint: "Fast and inexpensive" },
    { id: "gpt-4o", label: "GPT-4o", hint: "Higher accuracy, higher cost" },
  ],
  anthropic: [
    {
      id: "claude-haiku-4-5-20251001",
      label: "Claude Haiku 4.5",
      hint: "Fastest and cheapest",
    },
    {
      id: "claude-sonnet-5",
      label: "Claude Sonnet 5",
      hint: "Balanced accuracy and cost",
    },
    {
      id: "claude-opus-5",
      label: "Claude Opus 5",
      hint: "Highest accuracy, slowest and priciest",
    },
  ],
};

/** Sentinel value for the "type your own model ID" option. */
export const CUSTOM_MODEL = "__custom__";

export function modelPresets(provider: string): ModelPreset[] {
  return MODEL_PRESETS[provider] ?? [];
}

/** The default model to prefill when a provider is selected, if any. */
export function defaultModelFor(provider: string): string {
  const presets = modelPresets(provider);
  return presets.length ? presets[0].id : "";
}

export function presetFor(provider: string, model: string): ModelPreset | undefined {
  return modelPresets(provider).find((p) => p.id === model);
}

/**
 * Whether a model ID must be entered by hand: either the provider has no
 * presets at all, or the stored value isn't one of them (a project configured
 * before a preset existed, or a deliberately custom ID).
 */
export function isCustomModel(provider: string, model: string): boolean {
  const presets = modelPresets(provider);
  if (!presets.length) return true;
  return model !== "" && !presets.some((p) => p.id === model);
}

/**
 * Bedrock rejects Anthropic model IDs that lack a cross-region inference
 * profile prefix, with an error that doesn't say so. Warn at config time.
 */
export function bedrockModelWarning(provider: string, model: string): string | null {
  if (provider !== "bedrock" || !model.trim()) return null;
  if (/^(us|eu|apac|global|us-gov)\./.test(model)) return null;
  return (
    "Bedrock serves current Anthropic models only through cross-region inference " +
    "profiles. This ID will likely fail unless it is prefixed with a region " +
    `(e.g. "us.${model}").`
  );
}
