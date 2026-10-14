import { cleanup, fireEvent, render, screen, waitFor, within, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import AttemptReview from "./AttemptReview";
import type { AttemptMatches, AttemptResult, EvaluationAttempt } from "./v2Types";

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const root = "/projects/project/evaluation/sessions/session/v2";
const makeAttempt = (overrides: Partial<EvaluationAttempt> = {}): EvaluationAttempt => ({
  id: "first", sequence: 1, query_id: "query", prompt_revision_id: null,
  mode: "llm", scope: "sample", status: "completed", metrics: null,
  created_at: "2026-10-13T12:00:00Z", prompt_revision: null,
  query_revision: { id: "query", query: "DVT", revision: 1, exclude_negated: true, source_queries: [] },
  ...overrides,
});
const makeMatches = (id = "first", page = 1): AttemptMatches => ({
  notes: [{ note_id: `${id}-${page}`, patient_id: "patient", note_date: "2026-10-13",
    text: "Full context before DVT and context after.", sentences: [{ text: "DVT" }],
    matches: [{ token: "DVT", note_start_index: 20, note_end_index: 23 }] }],
  total_notes: 11, page, total_pages: 2,
});
let attempts: Record<string, EvaluationAttempt>;
let results: AttemptResult[];
const onRefresh = vi.fn();
const onCommitted = vi.fn();
function mount(attempt = attempts.first, permissions = { editable: true, reviewable: true }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = (selected: EvaluationAttempt) => <QueryClientProvider client={client}>
    <AttemptReview projectId="project" sessionId="session" initialAttempt={selected}
      {...permissions} onRefresh={onRefresh} onCommitted={onCommitted} />
  </QueryClientProvider>;
  return { client, ...render(view(attempt)), switchAttempt: (selected: EvaluationAttempt) => view(selected) };
}
beforeEach(() => {
  vi.resetAllMocks();
  attempts = { first: makeAttempt(), second: makeAttempt({ id: "second", sequence: 2 }) };
  results = [];
  vi.mocked(api.get).mockImplementation(async (path) => {
    const id = path.split("/attempts/")[1]?.split(/[/?]/)[0];
    if (path.includes("/matches?")) return makeMatches(id, Number(new URLSearchParams(path.split("?")[1]).get("page")));
    if (path.endsWith("/results")) return results;
    return attempts[id];
  });
  vi.mocked(api.post).mockImplementation(async (path) => {
    const id = path.split("/attempts/")[1]?.split("/")[0];
    attempts[id] = { ...attempts[id], status: path.endsWith("/cancel") ? "cancelled" : "queued" };
    return attempts[id];
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("attempt review", () => {
  it("shows eligible full-note context and offset highlights without model evidence", async () => {
    mount();
    const section = screen.getByRole("region", { name: "Matched notes" });
    fireEvent.click(await within(section).findByText(/Patient patient/));
    const fullText = section.querySelector("details p")!;
    expect(fullText).toHaveTextContent("Full context before DVT and context after.");
    expect(fullText.querySelector("mark")).toHaveTextContent("DVT");
    expect(screen.getByText("No cited note evidence")).toBeInTheDocument();
    expect(within(section).getByText(/11 matched notes total.*1 distinct patients.*1 keyword matches/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(`${root}/attempts/first/matches?page=1&page_size=10`);
  });

  it("paginates and isolates both attempt ID and page in the cache", async () => {
    const view = mount();
    await screen.findByText(/Note first-1/);
    expect(screen.getByRole("button", { name: "Previous matched notes page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next matched notes page" }));
    await screen.findByText(/Note first-2/);
    expect(screen.getByRole("button", { name: "Next matched notes page" })).toBeDisabled();
    expect(view.client.getQueryData(["eval-v2-matches", "project", "session", "first", 2])).toEqual(makeMatches("first", 2));
    view.rerender(view.switchAttempt(attempts.second));
    await screen.findByText(/Note second-1/);
    expect(screen.queryByText(/Note first-2/)).not.toBeInTheDocument();
    expect(view.client.getQueryData(["eval-v2-matches", "project", "session", "second", 1])).toEqual(makeMatches("second"));
  });

  it("merges overlapping offsets and ignores invalid offsets without losing text", async () => {
    const matched = makeMatches();
    matched.notes[0].matches.push({ token: "overlap", note_start_index: 21, note_end_index: 23 },
      { token: "invalid", note_start_index: -1, note_end_index: 99 });
    vi.mocked(api.get).mockImplementation(async (path) => path.includes("/matches?") ? matched
      : path.endsWith("/results") ? [] : attempts.first);
    mount();
    const summary = await screen.findByText(/Note first-1/);
    fireEvent.click(summary);
    expect(summary.parentElement!.querySelectorAll("mark")).toHaveLength(1);
    expect(summary.parentElement!.querySelector("p")).toHaveTextContent(matched.notes[0].text);
  });

  it.each([
    ["queued", "Cancel attempt", "cancel"], ["running", "Cancel attempt", "cancel"],
    ["cancelled", "Resume attempt", "resume"], ["failed", "Retry attempt", "retry"],
  ])("offers the correct control for %s and refreshes selected data", async (status, label, action) => {
    attempts.first = makeAttempt({ status, scope: "full", progress: { completed: 2, total: 10 } });
    const { client } = mount();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: label }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${root}/attempts/first/${action}`, {}));
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    for (const key of ["eval-v2-attempt", "eval-v2-results", "eval-v2-matches"]) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: [key, "project", "session", "first"] });
    }
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["eval-v2-state", "project", "session"] });
    expect(screen.getByRole("region", { name: "Attempt progress" })).toHaveTextContent("completed2total10");
  });

  it.each(["queued", "running", "cancelled", "failed", "completed"])("keeps recovery read-only for %s", async (status) => {
    attempts.first = makeAttempt({ status });
    mount(attempts.first, { editable: false, reviewable: false });
    await screen.findByText(/Note first-1/);
    expect(screen.queryByRole("button", { name: /Cancel attempt|Resume attempt|Retry attempt/ })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("does not expose recovery controls for a completed attempt", async () => {
    mount();
    await screen.findByText(/Note first-1/);
    expect(screen.queryByRole("button", { name: /Cancel attempt|Resume attempt|Retry attempt/ })).not.toBeInTheDocument();
  });

  it("disables recovery during a pending request", async () => {
    attempts.first = makeAttempt({ status: "cancelled" });
    let resolve!: (attempt: EvaluationAttempt) => void;
    vi.mocked(api.post).mockReturnValue(new Promise<EvaluationAttempt>((done) => { resolve = done; }));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Resume attempt" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume attempt" })).toBeDisabled());
    await act(async () => resolve(attempts.first));
  });

  it("surfaces failure and request errors without rendering clinical exception text", async () => {
    attempts.first = makeAttempt({ status: "failed", error_message: "PRIVATE CLINICAL CONTENT" });
    vi.mocked(api.post).mockRejectedValue(new Error("PRIVATE CLINICAL CONTENT"));
    mount();
    expect(screen.getByRole("alert")).toHaveTextContent("Attempt failed");
    fireEvent.click(screen.getByRole("button", { name: "Retry attempt" }));
    await screen.findByText("Unable to update the attempt. Try again.");
    expect(screen.queryByText(/PRIVATE CLINICAL CONTENT/)).not.toBeInTheDocument();
  });

  it("refreshes matched notes when a running attempt completes", async () => {
    attempts.first = makeAttempt({ status: "running" });
    const { client } = mount();
    await screen.findByText(/Note first-1/);
    vi.mocked(api.get).mockClear();
    attempts.first = makeAttempt();
    await act(async () => { client.setQueryData(["eval-v2-attempt", "project", "session", "first"], attempts.first); });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${root}/attempts/first/matches?page=1&page_size=10`));
  });

  it("retains annotator judgments with empty evidence without granting recovery permissions", async () => {
    results = [{ id: "result", patient_id: "patient", status: "completed", finding_label: "positive",
      finding_reasoning: "Synthetic finding", finding_evidence: [], review_judgment: null }];
    mount(attempts.first, { editable: false, reviewable: true });
    expect(await screen.findByRole("button", { name: "Correct" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Commit selected attempt" })).toBeDisabled();
    expect(await screen.findByText(/Note first-1/)).toBeInTheDocument();
  });
});