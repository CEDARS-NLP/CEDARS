import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/api/client";
import type { UnifiedSession } from "@/projects/types";
import SearchQueriesSection from "./SearchQueriesSection";

vi.mock("@/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/client")>();
  return { ...original, api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } };
});
vi.mock("./NotePreviewList", () => ({ default: () => <div>Matched notes</div> }));

const sessionPath = "/projects/project/evaluation/sessions/session/queries";
const impactPath = "/projects/project/nlp/reprocess-impact";
const jobPath = "/projects/project/nlp/job/status";
const zeroImpact = { annotations: 0, predictions: 0, sentences: 0 };
const existingImpact = { annotations: 3, predictions: 5, sentences: 8 };
const freshImpact = { annotations: 13, predictions: 21, sentences: 34 };
const clients: QueryClient[] = [];

function makeSession(): UnifiedSession {
  return {
    id: "session",
    project_id: "project",
    status: "draft",
    search_queries: [{ query: "DVT", type: "include" }],
    query_sections: [{ query: "DVT", type: "include" }],
    exclude_negated: true,
    event_name: null,
    event_description: null,
    include_criteria: null,
    exclude_criteria: null,
    sample_size: 5,
    metrics: null,
    committed_config: null,
    committed_at: null,
    cloned_from_id: null,
    created_by: "user",
    created_at: "2026-10-14T00:00:00Z",
    updated_at: "2026-10-14T00:00:00Z",
  };
}

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<Value>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function showSession(session = makeSession()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const callbacks = {
    onRefresh: vi.fn(),
    onQueriesSaved: vi.fn(),
    onSearchRun: vi.fn(),
    onContinue: vi.fn(),
  };
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SearchQueriesSection
          projectId="project"
          session={session}
          searchStale={false}
          matchedPatients={0}
          {...callbacks}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...callbacks };
}

function editSubqueries() {
  fireEvent.change(screen.getByRole("textbox", { name: "Query 1" }), {
    target: { value: "  DVT OR embol*  " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add query" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Query 2 type" }), {
    target: { value: "exclude" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Query 2" }), {
    target: { value: "  suspected  " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add query" }));
}

const cleanedQueries: UnifiedSession["search_queries"] = [
  { query: "DVT OR embol*", type: "include" },
  { query: "suspected", type: "exclude" },
];

function expectConfirmedImpact(impact: typeof existingImpact) {
  expect(api.post).toHaveBeenLastCalledWith(`${sessionPath}/run-all`, {
    confirmed: true,
    expected_annotations: impact.annotations,
    expected_predictions: impact.predictions,
    expected_sentences: impact.sentences,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.get).mockResolvedValue(zeroImpact);
  vi.mocked(api.put).mockResolvedValue(makeSession());
  vi.mocked(api.post).mockResolvedValue({ status: "completed" });
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.useRealTimers();
});

describe("SearchQueriesSection", () => {
  it("saves trimmed, nonempty subqueries before continuing without an event or provider", async () => {
    const save = deferred<UnifiedSession>();
    vi.mocked(api.put).mockReturnValueOnce(save.promise);
    const callbacks = showSession();
    editSubqueries();
    fireEvent.click(screen.getByRole("button", { name: "Continue to event definition" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(sessionPath, {
      search_queries: cleanedQueries,
      exclude_negated: true,
    }));
    expect(callbacks.onContinue).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    await act(async () => save.resolve({
      ...makeSession(),
      search_queries: [{ query: "(DVT OR embol*) AND !(suspected)", type: "include" }],
      query_sections: cleanedQueries,
    }));
    await waitFor(() => expect(callbacks.onContinue).toHaveBeenCalledExactlyOnceWith());
    expect(callbacks.onQueriesSaved).toHaveBeenCalledOnce();
  });

  it("saves dirty subqueries before fetching impact and running all patients", async () => {
    const save = deferred<UnifiedSession>();
    vi.mocked(api.put).mockReturnValueOnce(save.promise);
    showSession();
    editSubqueries();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(sessionPath, {
      search_queries: cleanedQueries,
      exclude_negated: true,
    }));
    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    await act(async () => save.resolve({
      ...makeSession(),
      search_queries: [{ query: "(DVT OR embol*) AND !(suspected)", type: "include" }],
      query_sections: cleanedQueries,
    }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${sessionPath}/run-all`, {}));
    expect(api.get).toHaveBeenCalledWith(impactPath);
  });

  it("keeps source sections visible while saving the normalized execution query", async () => {
    const normalized = {
      ...makeSession(),
      search_queries: [{ query: "(DVT OR embol*) AND !(suspected)", type: "include" as const }],
      query_sections: cleanedQueries,
    };
    vi.mocked(api.put).mockResolvedValueOnce(normalized);
    const { client, onContinue } = showSession();
    editSubqueries();
    fireEvent.click(screen.getByRole("button", { name: "Continue to event definition" }));

    await waitFor(() => expect(onContinue).toHaveBeenCalledOnce());
    expect(screen.getByRole("textbox", { name: "Query 1" })).toHaveValue("DVT OR embol*");
    expect(screen.getByRole("textbox", { name: "Query 2" })).toHaveValue("suspected");
    expect(screen.getByRole("combobox", { name: "Query 2 type" })).toHaveValue("exclude");
    expect(screen.getAllByRole("textbox")).toHaveLength(2);
    expect(api.put).toHaveBeenCalledWith(sessionPath, {
      search_queries: cleanedQueries,
      exclude_negated: true,
    });
    expect(client.getQueryData(["eval-session", "project", "session"])).toEqual(normalized);
  });

  it("loads saved source sections separately from the merged execution query", () => {
    const saved = {
      ...makeSession(),
      search_queries: [{ query: "(DVT OR embol*) AND !((suspected))", type: "include" as const }],
      query_sections: cleanedQueries,
    };
    showSession(saved);

    expect(screen.getByRole("textbox", { name: "Query 1" })).toHaveValue("DVT OR embol*");
    expect(screen.getByRole("textbox", { name: "Query 2" })).toHaveValue("suspected");
    expect(screen.getByRole("combobox", { name: "Query 2 type" })).toHaveValue("exclude");
  });

  it("shows one matched-notes preview for the saved query sections", () => {
    showSession({
      ...makeSession(),
      search_queries: [{ query: "(DVT OR embol*) AND !((suspected))", type: "include" }],
      query_sections: cleanedQueries,
    });

    fireEvent.click(screen.getByRole("button", { name: "Show matched notes" }));

    expect(screen.getByText("Matched notes")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Show matched notes" })).toHaveLength(1);
  });

  it("shows the negation checkbox checked by default", () => {
    showSession();
    expect(screen.getByRole("checkbox", { name: /Remove negated matches/ })).toBeChecked();
  });

  it("saves exclude_negated false when the checkbox is unchecked", async () => {
    const save = deferred<UnifiedSession>();
    vi.mocked(api.put).mockReturnValueOnce(save.promise);
    showSession();
    fireEvent.click(screen.getByRole("checkbox", { name: /Remove negated matches/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue to event definition" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(sessionPath, {
      search_queries: [{ query: "DVT", type: "include" }],
      exclude_negated: false,
    }));
    await act(async () => save.resolve({ ...makeSession(), exclude_negated: false }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Remove negated matches/ })).not.toBeChecked());
  });

  it("marks the session dirty when only the negation checkbox changes", () => {
    showSession();
    expect(screen.getByRole("button", { name: "Run search" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Remove negated matches/ }));
    expect(screen.getByRole("button", { name: "Save and run search" })).toBeInTheDocument();
  });

  it("runs a zero-impact search with an empty body and no event or provider", async () => {
    const { onRefresh } = showSession();
    expect(screen.getByRole("button", { name: "Suggest from event definition" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledExactlyOnceWith(`${sessionPath}/run-all`, {}));
    expect(api.put).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(onRefresh).toHaveBeenCalledOnce());
    expect(screen.getByRole("link", { name: "Review annotations" })).toHaveAttribute("href", "/projects/project/annotations");
  });

  it("shows existing impact counts and never runs when cancellation is selected", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact);
    showSession();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/3 annotations, 5 predictions, and 8 sentences/)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep existing results" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.post).not.toHaveBeenCalled();
  });

  it("fetches fresh counts on reopening and sends them on confirmation", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact).mockResolvedValueOnce(freshImpact);
    showSession();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));
    fireEvent.click(await screen.findByRole("button", { name: "Keep existing results" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/13 annotations, 21 predictions, and 34 sentences/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Replace and run" }));

    await waitFor(() => expectConfirmedImpact(freshImpact));
    expect(api.post).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("disables confirmation after a 409 until refreshed counts arrive, then sends those counts", async () => {
    const refresh = deferred<typeof existingImpact>();
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact).mockReturnValueOnce(refresh.promise);
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError("Search results changed", 409));
    showSession();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));
    fireEvent.click(await screen.findByRole("button", { name: "Replace and run" }));

    await waitFor(() => expect(api.get).toHaveBeenNthCalledWith(2, impactPath));
    const confirm = screen.getByRole("button", { name: "Replace and run" });
    expect(confirm).toBeDisabled();
    expect(screen.getByText("Search results changed")).toBeInTheDocument();
    fireEvent.click(confirm);
    expect(api.post).toHaveBeenCalledOnce();
    await act(async () => refresh.resolve(freshImpact));
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(within(screen.getByRole("dialog")).getByText(/13 annotations, 21 predictions, and 34 sentences/)).toBeInTheDocument();
    fireEvent.click(confirm);
    await waitFor(() => expectConfirmedImpact(freshImpact));
    expect(api.post).toHaveBeenCalledTimes(2);
  });

  it("keeps confirmation disabled and shows the error when the 409 impact refresh fails", async () => {
    const refresh = deferred<typeof existingImpact>();
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact).mockReturnValueOnce(refresh.promise);
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError("Search results changed", 409));
    showSession();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));
    fireEvent.click(await screen.findByRole("button", { name: "Replace and run" }));

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Replace and run" })).toBeDisabled();
    await act(async () => refresh.reject(new Error("Impact refresh failed")));
    expect(await screen.findByText("Impact refresh failed")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Replace and run" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(api.post).toHaveBeenCalledOnce();
  });

  it.each(["Continue to event definition", "Save and run search", "Run on all patients"])(
    "does not execute or continue after a failed save from %s",
    async (action) => {
      vi.mocked(api.put).mockRejectedValueOnce(new Error("Queries could not be saved"));
      const callbacks = showSession();
      editSubqueries();
      fireEvent.click(screen.getByRole("button", { name: action }));

      expect(await screen.findByText("Queries could not be saved")).toBeInTheDocument();
      expect(api.put).toHaveBeenCalledOnce();
      expect(api.post).not.toHaveBeenCalled();
      expect(api.get).not.toHaveBeenCalled();
      expect(callbacks.onContinue).not.toHaveBeenCalled();
      expect(callbacks.onSearchRun).not.toHaveBeenCalled();
      expect(callbacks.onQueriesSaved).not.toHaveBeenCalled();
      expect(callbacks.onRefresh).not.toHaveBeenCalled();
    },
  );

  it("shows initial impact errors without starting run-all", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Impact unavailable"));
    showSession();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));

    expect(await screen.findByText("Impact unavailable")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows run-all errors without starting background polling", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error("Search could not start"));
    const { onRefresh } = showSession();
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));

    expect(await screen.findByText("Search could not start")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith(jobPath);
    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each(["completed", "failed"])("polls a running background job until it is %s", async (status) => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    vi.mocked(api.get)
      .mockResolvedValueOnce(zeroImpact)
      .mockResolvedValueOnce({ status: "running", error_message: null })
      .mockResolvedValueOnce({ status, error_message: status === "failed" ? "Worker failed" : null });
    vi.mocked(api.post).mockResolvedValueOnce({ status: "pending" });
    showSession();
    expect(api.get).not.toHaveBeenCalledWith(jobPath);
    fireEvent.click(screen.getByRole("button", { name: "Run on all patients" }));

    expect(await screen.findByText("Searching all patients")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(jobPath));
    await waitFor(() => expect(screen.getByRole("button", { name: "Run on all patients" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Run search" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Continue to event definition" })).toBeDisabled();

    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(status === "completed" ? "Search complete" : "Search failed"));
    if (status === "failed") expect(screen.getByRole("status")).toHaveTextContent("Worker failed");
    expect(screen.getByRole("button", { name: "Run on all patients" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Continue to event definition" })).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(api.get).toHaveBeenCalledTimes(3);
  });
});