import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "@/api/client";
import AnnotationsPage from "./AnnotationsPage";

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const noteText = "DVT ruled out; DVT confirmed; DVT absent.";
let currentAnnotationId = "1";
let annotationRows: Record<string, unknown>[];

function annotation(id: string, start: number, end: number, reasoning: string) {
  return {
    id,
    project_id: "project",
    patient_id: "patient",
    note_id: "note",
    sentence_id: null,
    sentence_text: noteText,
    matched_tokens: "DVT",
    note_start_index: start,
    note_end_index: end,
    sentence_number: 0,
    sentence_start: 0,
    sentence_end: noteText.length,
    is_negated: false,
    predicted_score: 0.9,
    predicted_label: 1,
    reasoning,
    predictor_model: "test-model",
    review_status: id === "1" && currentAnnotationId === "2" ? "reviewed" : "unreviewed",
    event_date: null,
    created_at: "2026-01-01T00:00:00Z",
    note_date: "2026-01-01T00:00:00Z",
    note_text_id: "TEXT-1",
  };
}

function showAnnotations() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/project/annotations"]}>
        <Routes>
          <Route path="/projects/:projectId/annotations" element={<AnnotationsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  currentAnnotationId = "1";
  annotationRows = [
    annotation("1", 0, 3, "Prediction one"),
    annotation("2", 15, 18, "Prediction two"),
  ];
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path.endsWith("/annotations/stats")) {
      return { total: 2, unreviewed: 2, reviewed: 0, skipped: 0, events_found: 0, is_complete: false };
    }
    if (path.endsWith("/annotations/patient/next")) {
      return { patient_id: "patient", patient_id_ext: "P-1", total_annotations: 2, unreviewed_annotations: 2, all_complete: false };
    }
    if (path.endsWith("/annotations/patient/patient/annotations")) return annotationRows;
    if (path.endsWith("/annotations/patient/patient/cursor")) {
      return { current_annotation_id: currentAnnotationId, next_annotation_id: "2", annotation_ids: ["1", "2"] };
    }
    if (path.endsWith("/annotations/patient/patient/stats")) {
      return { total: 2, unreviewed: 2, reviewed: 0, skipped: 0, current_event_date: null, event_annotation_id: null };
    }
    if (path.endsWith("/annotations/1/context") || path.endsWith("/annotations/2/context")) {
      return {
        note_id: "note",
        patient_id: "patient",
        patient_id_ext: "P-1",
        text: noteText,
        text_id: "TEXT-1",
        note_date: "2026-01-01T00:00:00Z",
        note_tags: {},
        search_keywords: ["DVT"],
        current_note_evidence: [{ start: 15, end: 18, text: "DVT" }],
        annotation_spans: [
          { annotation_id: "1", start: 0, end: 3, sentence_start: 0, sentence_end: noteText.length, sentence_number: 0, is_negated: false },
          { annotation_id: "2", start: 15, end: 18, sentence_start: 0, sentence_end: noteText.length, sentence_number: 0, is_negated: false },
        ],
        sentences: [],
      };
    }
    throw new Error(`Unexpected GET ${path}`);
  });
  vi.mocked(api.post).mockImplementation(async (path) => {
    if (path.endsWith("/annotations/1/review")) {
      currentAnnotationId = "2";
      annotationRows = [
        { ...annotationRows[0], review_status: "reviewed" },
        annotationRows[1],
      ];
      return {
        annotation: annotationRows[0],
        skipped_count: 0,
        earlier_count: 0,
        current_annotation_id: "1",
        next_annotation_id: "1",
      };
    }
    throw new Error(`Unexpected POST ${path}`);
  });
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: vi.fn() });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("manual annotation review", () => {
  it("follows the backend-selected cursor after review", async () => {
    const { container } = showAnnotations();

    expect(await screen.findByText("Prediction one")).toBeInTheDocument();
    await waitFor(() => {
      expect([...container.querySelectorAll('mark[class*="bg-primary/15"]')].map((mark) => mark.textContent)).toEqual([
        "DVT", "DVT", "DVT", "DVT",
      ]);
      expect(container.querySelectorAll('mark[class*="bg-amber-200/70"]')).toHaveLength(4);
      expect([...container.querySelectorAll("mark")].some((mark) => mark.textContent === "DVT absent")).toBe(false);
      expect(container.querySelector('[data-llm-evidence="true"]')).toHaveTextContent("DVT");
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /No Event/ }));
    });

    await waitFor(() => expect(screen.getByText("Prediction two")).toBeInTheDocument());
    expect(api.get).toHaveBeenCalledWith("/projects/project/annotations/patient/patient/cursor");
  });
});