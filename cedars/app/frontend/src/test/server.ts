import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const server = setupServer(
  http.get("/api/v1/auth/me", () =>
    HttpResponse.json({ username: "tester", is_admin: false }),
  ),
  http.post("/api/v1/auth/logout", () => HttpResponse.json({ message: "ok" })),
  http.get("/api/v1/projects/:projectId", () =>
    HttpResponse.json({
      id: "project-1",
      name: "Project One",
      description: "Demo project",
      owner: "tester",
      role: "admin",
      created_at: "2024-01-01T00:00:00Z",
    }),
  ),
);
