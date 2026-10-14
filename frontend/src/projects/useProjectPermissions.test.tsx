import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import useProjectPermissions from "./useProjectPermissions";

const auth = vi.hoisted(() => ({ user: { platform_role: "user" } }));
vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/api/client", () => ({ api: { get: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); auth.user.platform_role = "user"; });
describe("project permissions", () => {
  it.each([
    ["admin", true, true], ["annotator", false, true], ["viewer", false, false],
    [null, false, false],
  ])("gates project role %s", async (role, canManage, canReview) => {
    vi.mocked(api.get).mockResolvedValue({ role });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useProjectPermissions("project"), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    await waitFor(() => expect(client.getQueryData(["project", "project"])).toEqual({ role }));
    await waitFor(() => expect(result.current).toEqual({ canManage, canReview }));
  });
  it("allows platform administrators without a project role", async () => {
    auth.user.platform_role = "platform_admin";
    vi.mocked(api.get).mockResolvedValue({ role: null });
    const client = new QueryClient();
    const { result } = renderHook(() => useProjectPermissions("project"), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    expect(result.current).toEqual({ canManage: true, canReview: true });
  });
});