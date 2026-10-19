import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import EvaluationSessionPage from "./EvaluationSessionPage";
import { api } from "@/api/client";
import type { FunnelStats } from "@/projects/types";

vi.mock("@/api/client", () => ({ api: { get: vi.fn() } }));
vi.mock("./SearchQueriesSection", () => ({ default: ({ onQueriesSaved }: { onQueriesSaved: () => void }) =>
  <div>Query editor<button onClick={onQueriesSaved}>Save query</button></div> }));
vi.mock("./EventDefinitionSection", () => ({ default: () => <div>Event editor</div> }));
vi.mock("./SampleRunSection", () => ({ default: () => <div>Model runner</div> }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function showSession(queries: { query: string; type: string }[] = [], event: string | null = null) {
  const funnel: FunnelStats = {
    sample_patients: 5,
    sample_notes: 10,
    matched_patients: 0,
    matched_notes: 0,
    filter_percent: 100,
    llm_positive: null,
    llm_negative: null,
    llm_inconclusive: null,
    estimated_cost: null,
  };
  vi.mocked(api.get).mockImplementation(async (path) => path.endsWith("/funnel")
    ? funnel
    : { id: "session", status: "draft", search_queries: queries, event_name: event, metrics: null });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/project/evaluation/session"]}>
    <Routes><Route path="/projects/:projectId/evaluation/:sessionId" element={<EvaluationSessionPage />} /></Routes>
  </MemoryRouter></QueryClientProvider>);
  return client;
}

describe("query-first evaluation", () => {
  it("opens the query editor before event definition", async () => {
    showSession();
    expect(await screen.findByText("Query editor")).toBeInTheDocument();
    const search = screen.getByRole("button", { name: /Apply Search Query/ });
    const event = screen.getByRole("button", { name: /^Define the event/ });
    expect(search.compareDocumentPosition(event) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(event).toBeDisabled();
    expect(screen.queryByText("Event editor")).not.toBeInTheDocument();
  });

  it("unlocks event entry with a saved query even with zero sample matches", async () => {
    showSession([{ query: "DVT", type: "include" }]);
    expect(await screen.findByText("Event editor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Test the model on a sample/ })).toBeDisabled();
  });

  it("keeps the query step mounted after saving for the full-run confirmation", async () => {
    const client = showSession();
    fireEvent.click(await screen.findByRole("button", { name: "Save query" }));
    await act(async () => {
      client.setQueryData(["eval-session", "project", "session"], {
        id: "session", status: "draft", search_queries: [{ query: "DVT", type: "include" }], event_name: null, metrics: null,
      });
    });
    expect(screen.getByText("Query editor")).toBeInTheDocument();
    expect(screen.queryByText("Event editor")).not.toBeInTheDocument();
  });
});