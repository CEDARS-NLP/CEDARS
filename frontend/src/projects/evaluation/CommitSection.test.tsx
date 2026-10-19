import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/api/client";
import type { CommitResult, SessionCost, UnifiedSession } from "@/projects/types";
import CommitSection from "./CommitSection";

vi.mock("@/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/client")>();
  return { ...original, api: { get: vi.fn(), post: vi.fn() } };
});

const impactPath = "/projects/project/nlp/reprocess-impact";
const commitPath = "/projects/project/evaluation/sessions/session/commit";
const zeroImpact = { annotations: 0, predictions: 0, sentences: 0 };
const existingImpact = { annotations: 13, predictions: 21, sentences: 34 };
const clients: QueryClient[] = [];

function makeSession(): UnifiedSession {
  return {
    id: "session",
    project_id: "project",
    status: "reviewing",
    search_queries: [{ query: "DVT", type: "include" }],
    query_sections: [{ query: "DVT", type: "include" }],
    exclude_negated: true,
    event_name: "Deep vein thrombosis",
    event_description: null,
    include_criteria: null,
    exclude_criteria: null,
    sample_size: 5,
    metrics: null,
    committed_config: null,
    committed_at: null,
    cloned_from_id: null,
    created_by: "user",
    created_at: "2026-10-16T00:00:00Z",
    updated_at: "2026-10-16T00:00:00Z",
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

function showSession(cost?: SessionCost) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const onRefresh = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <CommitSection projectId="project" session={makeSession()} onRefresh={onRefresh} cost={cost} />
    </QueryClientProvider>,
  );
  return { client, onRefresh };
}

function openConfirmation() {
  fireEvent.click(screen.getByRole("button", { name: "Save and process all patients" }));
}

function confirmButton() {
  return screen.getByRole("button", { name: "Run on all patients" });
}

function expectPayload(impact: typeof zeroImpact) {
  expect(api.post).toHaveBeenLastCalledWith(commitPath, {
    reprocess: {
      confirmed: true,
      expected_annotations: impact.annotations,
      expected_predictions: impact.predictions,
      expected_sentences: impact.sentences,
    },
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.get).mockResolvedValue(zeroImpact);
  vi.mocked(api.post).mockResolvedValue({ total_patients: 25, estimated_cost: null });
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

describe("CommitSection", () => {
  it("fetches impact only when opened and blocks submission until the preview succeeds", async () => {
    const preview = deferred<typeof zeroImpact>();
    vi.mocked(api.get).mockReturnValueOnce(preview.promise);
    showSession();
    expect(api.get).not.toHaveBeenCalled();
    openConfirmation();

    await waitFor(() => expect(api.get).toHaveBeenCalledExactlyOnceWith(impactPath));
    expect(screen.getByRole("status")).toHaveTextContent("Checking existing results");
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(api.post).not.toHaveBeenCalled();
    await act(async () => preview.resolve(zeroImpact));
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(api.post).not.toHaveBeenCalled();
  });

  it("shows result loss and fetches fresh counts after cancellation without posting", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact).mockResolvedValueOnce(zeroImpact);
    showSession();
    openConfirmation();

    expect(await screen.findByText(/This replaces 13 annotations, 21 predictions, and 34 sentences/)).toBeInTheDocument();
    expect(screen.getByText(/You will lose existing project results and review decisions/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.post).not.toHaveBeenCalled();
    openConfirmation();
    expect(await screen.findByText("No existing project results or review decisions to replace.")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/You will lose existing project results/)).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("allows cancellation while the impact preview is pending without posting", async () => {
    const preview = deferred<typeof zeroImpact>();
    vi.mocked(api.get).mockReturnValueOnce(preview.promise);
    showSession();
    openConfirmation();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => preview.resolve(existingImpact));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each([existingImpact, zeroImpact])("posts the exact confirmed preview payload for %j", async (impact) => {
    vi.mocked(api.get).mockResolvedValueOnce(impact);
    showSession();
    openConfirmation();
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());

    await waitFor(() => expectPayload(impact));
    expect(api.post).toHaveBeenCalledOnce();
  });

  it.each([existingImpact, zeroImpact])("requires explicit reconfirmation after a 409 refresh to %j", async (impact) => {
    const refresh = deferred<typeof zeroImpact>();
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact).mockReturnValueOnce(refresh.promise);
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError("Search results changed", 409));
    const { onRefresh } = showSession();
    openConfirmation();
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());

    await waitFor(() => expect(api.get).toHaveBeenNthCalledWith(2, impactPath));
    expect(screen.getByRole("alert")).toHaveTextContent("Project results changed. Review the updated counts and confirm again.");
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(api.post).toHaveBeenCalledOnce();
    expect(onRefresh).not.toHaveBeenCalled();
    await act(async () => refresh.resolve(impact));
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(api.post).toHaveBeenCalledOnce();
    if (impact.sentences === 0) {
      expect(screen.getByText("No existing project results or review decisions to replace.")).toBeInTheDocument();
    }
    fireEvent.click(confirmButton());
    await waitFor(() => expectPayload(impact));
    expect(api.post).toHaveBeenCalledTimes(2);
  });

  it("blocks confirmation after an initial preview error and supports an explicit preview retry", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Impact unavailable"));
    const { onRefresh } = showSession();
    openConfirmation();

    expect(await screen.findByText("Impact unavailable")).toBeInTheDocument();
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(api.post).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("blocks stale confirmation if the conflict preview refresh fails", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(existingImpact).mockRejectedValueOnce(new Error("Impact refresh failed"));
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError("Search results changed", 409));
    showSession();
    openConfirmation();
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());

    expect(await screen.findByText("Impact refresh failed")).toBeInTheDocument();
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(api.post).toHaveBeenCalledOnce();
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("shows other commit errors without refreshing impact, invalidating caches, or retrying", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError("Commit failed", 500));
    const { client, onRefresh } = showSession();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    openConfirmation();
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("Commit failed");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledOnce();
    expect(api.get).toHaveBeenCalledOnce();
    expect(invalidate).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    openConfirmation();
    expect(screen.queryByText("Commit failed")).not.toBeInTheDocument();
  });

  it("preserves the cost and lock confirmation and blocks dismissal during commit", async () => {
    const commit = deferred<CommitResult>();
    vi.mocked(api.post).mockReturnValueOnce(commit.promise);
    showSession({
      provider: "test",
      model: "test",
      spent_prompt_tokens: 0,
      spent_completion_tokens: 0,
      spent_cost: 0,
      projection: {
        basis: "sample",
        sample_patients_classified: 5,
        total_patients: 25,
        projected_matched_patients: 20,
        patients_to_classify: 15,
        tokens_per_patient: 100,
        prompt_tokens: 1000,
        completion_tokens: 500,
        estimated_cost: 1.5,
      },
    });
    openConfirmation();
    expect(screen.getByText(/This locks the queries and event definition/)).toBeInTheDocument();
    expect(screen.getByText("Patients in the project").nextElementSibling).toHaveTextContent("25");
    expect(screen.getByText("Still to send to the model").nextElementSibling).toHaveTextContent("15");
    expect(screen.getByText("Estimated cost").nextElementSibling).toHaveTextContent("1.50");
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());
    const committing = await screen.findByRole("button", { name: "Committing" });
    expect(committing).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    fireEvent.click(committing);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledOnce();
    await act(async () => commit.resolve({
      session: makeSession(),
      pipeline_run_id: "run",
      total_patients: 25,
      estimated_cost: 1.5,
      cost_basis: "sample",
    }));
    expect(await screen.findByText(/Started. Processing 25 patients/)).toBeInTheDocument();
  });

  it("closes on success, refreshes the caller, and invalidates project and current evaluation caches", async () => {
    const { client, onRefresh } = showSession();
    const projectKeys = [
      "nlp-queries", "nlp-stats", "nlp-background-job", "annotation-stats",
      "project-stats", "project", "eval-sessions",
    ].map((key) => [key, "project"]);
    const evaluationKeys = [
      "eval-session", "eval-results", "eval-metrics", "eval-next-result",
      "eval-result-notes", "funnel", "cost",
    ].map((key) => [key, "project", "session"]);
    const keys = [...projectKeys, ...evaluationKeys, ["annotation-context", "annotation"]];
    keys.forEach((key) => client.setQueryData(key, { cached: true }));
    client.setQueryData(["eval-session", "project", "other-session"], { cached: true });
    client.setQueryData(["project-stats", "other-project"], { cached: true });
    openConfirmation();
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onRefresh).toHaveBeenCalledExactlyOnceWith());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(/Started. Processing 25 patients/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save and process all patients" })).toBeDisabled();
    keys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true));
    expect(client.getQueryState(["eval-session", "project", "other-session"])?.isInvalidated).toBe(false);
    expect(client.getQueryState(["project-stats", "other-project"])?.isInvalidated).toBe(false);
  });
});