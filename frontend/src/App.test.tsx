import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  it("sends an unauthenticated visitor to the login page", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    window.history.pushState({}, "", "/projects");
    render(<App />);
    expect(await screen.findByText("Welcome back", {}, { timeout: 15000 })).toBeInTheDocument();
  }, 30000);
});
