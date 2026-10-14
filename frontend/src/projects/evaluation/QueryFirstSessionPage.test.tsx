import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import type { UnifiedSession } from "@/projects/types";
import QueryFirstSessionPage from "./QueryFirstSessionPage";
import type { AttemptResult, EvaluationAttempt, EvaluationState, PromptRevision, QueryRevision } from "./v2Types";

const access = vi.hoisted(() => ({ canManage: true, canReview: true }));
vi.mock("@/projects/useProjectPermissions", () => ({ default: () => access }));
vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

const root = "/projects/project/evaluation/sessions/session";
const query: QueryRevision = {
  id: "query-1", query: "((DVT)) AND NOT ((suspected))", revision: 1, exclude_negated: true,
  source_queries: [{ query: "DVT", type: "include" }, { query: "suspected", type: "exclude" }],
};
const prompt: PromptRevision = {
  id: "prompt-1", revision: 1, event_name: "Thrombosis", event_description: "Confirmed thrombosis",
  include_criteria: "Confirmed diagnosis", exclude_criteria: "Rule-out diagnosis",
  llm_provider: "bedrock", llm_model: "model-1",
};
const attempt = (id: string, sequence: number, overrides: Partial<EvaluationAttempt> = {}): EvaluationAttempt => ({
  id, sequence, query_id: query.id, prompt_revision_id: prompt.id,
  mode: "llm", scope: "sample", status: "completed", metrics: { accuracy: 1, total_reviewed: 1 },
  created_at: "2026-10-13T12:00:00Z", query_revision: query, prompt_revision: prompt, ...overrides,
});
const result = (patientId: string): AttemptResult => ({
  id: `result-${patientId}`, patient_id: patientId, status: "completed", finding_label: "positive",
  finding_confidence: 0.9, finding_reasoning: "Confirmed thrombosis", review_judgment: "correct",
  finding_evidence: [{ note_id: `note-${patientId}`, text: "Documented DVT" }],
});
const session = { id: "session", status: "draft", workflow_version: 2 } as UnifiedSession;
let state: EvaluationState;
let results: Record<string, AttemptResult[]>;

function renderPage(status: UnifiedSession["status"] = "draft") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter>
    <QueryFirstSessionPage projectId="project" session={{ ...session, status }} />
  </MemoryRouter></QueryClientProvider>);
  return client;
}

beforeEach(() => {
  vi.resetAllMocks();
  access.canManage = true;
  access.canReview = true;
  state = { query_revision: null, prompt_revision: null, attempts: [] };
  results = {};
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === `${root}/v2/state`) return structuredClone(state);
    const id = path.split("/attempts/")[1]?.split("/")[0];
    if (path.endsWith("/results")) return structuredClone(results[id] ?? []);
    if (id) return structuredClone(state.attempts.find((item) => item.id === id));
    throw new Error(`Unexpected GET ${path}`);
  });
  vi.mocked(api.put).mockImplementation(async (path, body) => {
    if (path.endsWith("/queries")) {
      const payload = body as { search_queries: QueryRevision["source_queries"]; exclude_negated: boolean };
      state.query_revision = { ...query, id: "query-2", revision: 2, source_queries: payload.search_queries,
        exclude_negated: payload.exclude_negated, query: "((PE))" };
      return structuredClone(state.query_revision);
    }
    state.prompt_revision = { ...prompt, ...(body as object), id: "prompt-2", revision: 2 };
    return structuredClone(state.prompt_revision);
  });
  vi.mocked(api.post).mockImplementation(async (path) => {
    if (path.includes("/judge")) return result("old");
    const next = attempt(`attempt-${state.attempts.length + 1}`, state.attempts.length + 1, {
      query_id: state.query_revision?.id ?? query.id,
      query_revision: state.query_revision ?? query,
      prompt_revision: state.prompt_revision,
      prompt_revision_id: state.prompt_revision?.id ?? null,
      mode: path.endsWith("run-llm") || path.endsWith("commit") ? "llm" : "search",
      scope: path.endsWith("run-all") || path.endsWith("commit") ? "full" : "sample",
    });
    state.attempts.push(next);
    return structuredClone(next);
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("query-first session", () => {
  it("starts with queries and negation exclusion, without event fields or unlocked branches", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Untitled session" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Exclude negated keywords" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save queries" })).toBeDisabled();
    expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run on all patients" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Query 1 type"), { target: { value: "exclude" } });
    fireEvent.change(screen.getByLabelText("Query 1", { exact: true }), { target: { value: "DVT" } });
    expect(screen.getByRole("button", { name: "Save queries" })).toBeDisabled();
  });

  it("saves include/exclude rows and the negation flag, then unlocks both branches without preview", async () => {
    renderPage();
    const input = await screen.findByLabelText("Query 1", { exact: true });
    fireEvent.change(input, { target: { value: " DVT " } });
    fireEvent.click(screen.getByRole("button", { name: "Add query" }));
    fireEvent.change(screen.getByLabelText("Query 2 type"), { target: { value: "exclude" } });
    fireEvent.change(screen.getByLabelText("Query 2", { exact: true }), { target: { value: "suspected" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Exclude negated keywords" }));
    fireEvent.click(screen.getByRole("button", { name: "Save queries" }));
    expect(await screen.findByRole("button", { name: "Run on all patients" })).toBeEnabled();
    expect(api.put).toHaveBeenCalledWith(`${root}/v2/queries`, {
      search_queries: query.source_queries, exclude_negated: false,
    });
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${root}/v2/run-all`, { query_id: "query-2" }));
    expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument();
  });

  it("keeps branches locked when canonical validation rejects a query", async () => {
    vi.mocked(api.put).mockRejectedValue(new Error("Enter a valid query expression"));
    renderPage();
    fireEvent.change(await screen.findByLabelText("Query 1", { exact: true }), { target: { value: "DVT AND" } });
    fireEvent.click(screen.getByRole("button", { name: "Save queries" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a valid query expression");
    expect(screen.queryByRole("button", { name: "Define an event" })).not.toBeInTheDocument();
  });

  it("defines an event after queries and runs an LLM sample without a preview request", async () => {
    state.query_revision = query;
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Define an event" }));
    fireEvent.change(screen.getByLabelText("Event name"), { target: { value: "Thrombosis" } });
    fireEvent.click(screen.getByRole("button", { name: "Save event" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run LLM sample" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${root}/v2/run-llm`, {
      query_id: query.id, prompt_revision_id: "prompt-2",
    }));
    expect(api.post).not.toHaveBeenCalledWith(`${root}/v2/preview`, expect.anything());
  });

  it("requires saving query edits before another LLM run without changing selected history", async () => {
    state = { query_revision: query, prompt_revision: prompt, attempts: [attempt("old", 1)] };
    results.old = [result("old")];
    renderPage();
    await screen.findByRole("button", { name: "Run LLM sample" });
    fireEvent.change(screen.getByLabelText("Query 1", { exact: true }), { target: { value: "PE" } });
    expect(screen.getByRole("button", { name: "Run LLM sample" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Run on all patients" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Selected attempt")).toHaveValue("old");
  });

  it("preserves the selected old attempt after a new query save and commits its ID", async () => {
    const old = attempt("old", 1);
    const latest = attempt("latest", 2, { query_revision: { ...query, id: "query-new", revision: 2 } });
    state = { query_revision: latest.query_revision, prompt_revision: prompt, attempts: [old, latest] };
    results = { old: [result("old")], latest: [result("latest")] };
    const client = renderPage();
    await screen.findByLabelText("Selected attempt");
    fireEvent.change(screen.getByLabelText("Selected attempt"), { target: { value: "old" } });
    expect(await screen.findByText("Judgment: correct")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Query 1", { exact: true }), { target: { value: "PE" } });
    fireEvent.click(screen.getByRole("button", { name: "Save queries" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    expect(screen.getByLabelText("Selected attempt")).toHaveValue("old");
    expect(within(screen.getByLabelText("Selected attempt revisions")).getByText(/Query revision 1/)).toBeInTheDocument();
    expect(client.getQueryData(["eval-v2-results", "project", "session", "old"])).toEqual([result("old")]);
    fireEvent.click(screen.getByRole("button", { name: "Commit selected attempt" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${root}/v2/commit`, { attempt_id: "old" }));
    expect(state.attempts).toHaveLength(3);
  });

  it("scopes judgments and evidence to the selected attempt", async () => {
    state = { query_revision: query, prompt_revision: prompt, attempts: [attempt("old", 1), attempt("latest", 2)] };
    results = { old: [result("old")], latest: [result("latest")] };
    renderPage();
    await screen.findByLabelText("Selected attempt");
    fireEvent.change(screen.getByLabelText("Selected attempt"), { target: { value: "old" } });
    await screen.findByText("Patient old | Note note-old");
    expect(screen.queryByText("Patient latest | Note note-latest")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Wrong" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${root}/v2/attempts/old/results/result-old/judge`, {
      judgment: "wrong", event_date_override: null,
    }));
  });

  it.each(["viewer", "annotator"])("keeps %s query and event editors read-only", async (role) => {
    access.canManage = false;
    access.canReview = role === "annotator";
    state = { query_revision: query, prompt_revision: prompt, attempts: [attempt("old", 1)] };
    results.old = [result("old")];
    renderPage();
    expect(await screen.findByLabelText("Query 1", { exact: true })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Exclude negated keywords" })).toBeDisabled();
    expect(screen.getByLabelText("Event name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run on all patients" })).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Commit selected attempt" })).toBeDisabled();
    await screen.findByText("Judgment: correct");
    expect(!!screen.queryByRole("button", { name: "Correct" })).toBe(role === "annotator");
  });

  it("retains history but locks completed sessions", async () => {
    state = { query_revision: query, prompt_revision: prompt, attempts: [attempt("old", 1)] };
    results.old = [result("old")];
    renderPage("completed");
    expect(await screen.findByLabelText("Query 1", { exact: true })).toBeDisabled();
    expect(await screen.findByText("Judgment: correct")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit selected attempt" })).toBeDisabled();
  });

  it("accepts a zero-match preview and blocks commit of an all-failed attempt", async () => {
    state = { query_revision: query, prompt_revision: null, attempts: [attempt("preview", 1, {
      mode: "search", prompt_revision: null, prompt_revision_id: null, metrics: { matched_notes: 0 },
    })] };
    renderPage();
    expect(await screen.findByRole("button", { name: "Run on all patients" })).toBeEnabled();
    expect(await screen.findByText("No saved results")).toBeInTheDocument();
    cleanup();
    state = { query_revision: query, prompt_revision: prompt, attempts: [attempt("failed", 2)] };
    results.failed = [{ ...result("failed"), status: "failed" }];
    renderPage();
    expect(await screen.findByRole("button", { name: "Commit selected attempt" })).toBeDisabled();
  });
});