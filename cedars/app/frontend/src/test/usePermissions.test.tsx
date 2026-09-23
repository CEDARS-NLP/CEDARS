import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useProjectPermissions } from "../projects/usePermissions";

describe("useProjectPermissions", () => {
  function wrapper(role: "investigator" | "admin" | "annotator") {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    return renderHook(() => useProjectPermissions(), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/projects/project-1"]}>
            <Routes>
              <Route
                path="/projects/:projectId"
                element={
                  <Outlet context={{ project: { id: "project-1", name: "Demo", description: "", owner: "tester", role, created_at: "2024-01-01T00:00:00Z" } }} />
                }
              >
                <Route index element={<>{children}</>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      ),
    });
  }

  it("returns admin-level permissions for admin and investigator roles", () => {
    const admin = wrapper("admin");
    expect(admin.result.current.isAdminLevel).toBe(true);
    expect(admin.result.current.canManageMembers).toBe(true);
    expect(admin.result.current.canRunJobs).toBe(true);

    const investigator = wrapper("investigator");
    expect(investigator.result.current.isAdminLevel).toBe(true);
  });

  it("limits power for annotator roles", () => {
    const annotator = wrapper("annotator");
    expect(annotator.result.current.isAdminLevel).toBe(false);
    expect(annotator.result.current.canManageMembers).toBe(false);
    expect(annotator.result.current.canRunJobs).toBe(false);
    expect(annotator.result.current.canAdjudicate).toBe(true);
  });
});
