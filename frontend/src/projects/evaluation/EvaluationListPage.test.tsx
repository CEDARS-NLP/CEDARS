import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import EvaluationListPage from "./EvaluationListPage";

const access = vi.hoisted(() => ({ canManage: true, canReview: true }));
vi.mock("@/projects/useProjectPermissions", () => ({ default: () => access }));
vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/projects/project/evaluation"]}><Routes>
      <Route path="/projects/:projectId/evaluation" element={<EvaluationListPage />} />
      <Route path="/projects/:projectId/evaluation/:sessionId" element={<p>Session detail</p>} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => { vi.resetAllMocks(); access.canManage = true; vi.mocked(api.get).mockResolvedValue([]); });
afterEach(cleanup);
describe("evaluation session entry", () => {
  it("has one create entry and no standalone search or mode cards", async () => {
    vi.mocked(api.post).mockResolvedValue({ id: "new", workflow_version: 2 });
    mount();
    await screen.findByText("No evaluation sessions yet");
    expect(screen.getAllByRole("button", { name: "Create evaluation session" })).toHaveLength(1);
    expect(screen.queryByText("Run a search query")).not.toBeInTheDocument();
    expect(screen.queryByText("Test an LLM filter first")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create evaluation session" }));
    expect(await screen.findByText("Session detail")).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/projects/project/evaluation/sessions", {
      search_queries: [], workflow_version: 2,
    });
  });
  it("disables creation for a read-only role", async () => {
    access.canManage = false;
    mount();
    await screen.findByText("No evaluation sessions yet");
    expect(screen.getByRole("button", { name: "Create evaluation session" })).toBeDisabled();
  });
  it("preserves active and committed session guards", async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: "active", status: "committed", event_name: null,
      search_queries: [], sample_size: 0, created_at: "2026-10-13" }]);
    mount();
    await screen.findByText("Untitled session");
    expect(screen.getByRole("button", { name: "Create evaluation session" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clone to new session" })).toBeDisabled();
  });
  it("clones into workflow version two", async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: "old", status: "completed", event_name: null,
      search_queries: [], sample_size: 0, created_at: "2026-10-13" }]);
    vi.mocked(api.post).mockResolvedValue({ id: "cloned", workflow_version: 2 });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Clone to new session" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/projects/project/evaluation/sessions/old/clone", { workflow_version: 2 }));
  });
});