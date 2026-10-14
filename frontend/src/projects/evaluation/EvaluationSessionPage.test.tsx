import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import EvaluationSessionPage from "./EvaluationSessionPage";

vi.mock("@/api/client", () => ({ api: { get: vi.fn() } }));
vi.mock("./QueryFirstSessionPage", () => ({ default: () => <p>Query-first renderer</p> }));
vi.mock("./EventDefinitionSection", () => ({ default: () => <p>Legacy event editor</p> }));
vi.mock("./FunnelBar", () => ({ default: () => null }));

function mount(version?: number) {
  vi.mocked(api.get).mockImplementation(async (path) => path.endsWith("/funnel") ? {} : {
    id: "session", workflow_version: version, status: "draft", search_queries: [], metrics: null,
  });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/projects/project/evaluation/session"]}><Routes>
      <Route path="/projects/:projectId/evaluation/:sessionId" element={<EvaluationSessionPage />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.resetAllMocks(); });
describe("workflow-version routing", () => {
  it("routes version two without legacy funnel requests", async () => {
    mount(2);
    expect(await screen.findByText("Query-first renderer")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining("/funnel"));
    expect(screen.queryByText("Legacy event editor")).not.toBeInTheDocument();
  });
  it.each([1, undefined])("keeps version %s on the legacy renderer", async (version) => {
    mount(version);
    expect(await screen.findByText("Legacy event editor")).toBeInTheDocument();
    expect(screen.queryByText("Query-first renderer")).not.toBeInTheDocument();
  });
});