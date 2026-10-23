import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "@/api/client";
import ExportPage from "./ExportPage";

vi.mock("@/api/client", () => ({ api: { get: vi.fn() } }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function showExportPage() {
  vi.mocked(api.get).mockResolvedValue({ total: 12, reviewed: 7, events: 2, total_eval_tokens: 0 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/project/export"]}>
        <Routes>
          <Route path="/projects/:projectId/export" element={<ExportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("manual export", () => {
  it("defaults to patient RESULTS and only shows annotation filters for annotation export", async () => {
    showExportPage();

    expect(await screen.findByRole("radio", { name: "Patient RESULTS" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: "Download patient RESULTS" })).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Annotation filter" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Annotations" }));
    expect(screen.getByRole("radiogroup", { name: "Annotation filter" })).toBeInTheDocument();
  });
});