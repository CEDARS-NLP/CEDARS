import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "@/api/client";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

// ── Types ───────────────────────────────────────────────────────

interface Patient {
  id: string;
  patient_id_ext: string;
  status: string;
  note_count: number;
  annotation_count: number;
  reviewed_count: number;
  created_at: string;
  updated_at: string;
}

interface PatientListResponse {
  items: Patient[];
  total: number;
  limit: number;
  offset: number;
}

// ── Helpers ─────────────────────────────────────────────────────

const PAGE_SIZE = 20;

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "new", label: "New" },
  { value: "nlp_processing", label: "NLP Processing" },
  { value: "nlp_complete", label: "NLP Complete" },
  { value: "reviewing", label: "Reviewing" },
  { value: "reviewed", label: "Reviewed" },
];

function statusBadgeVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "reviewed":
      return "default";
    case "reviewing":
      return "secondary";
    default:
      return "outline";
  }
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Component ───────────────────────────────────────────────────

export default function PatientsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const { data, isLoading } = useQuery<PatientListResponse>({
    queryKey: ["patients", projectId, search, status, offset],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (search) params.set("search", search);
      if (status) params.set("status", status);
      return api.get(`/projects/${projectId}/data/patients?${params}`);
    },
    enabled: !!projectId,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="data" projectId={projectId!} />

      <div>
        <h1 className="text-2xl font-semibold">Patients</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Search and browse patients. View notes and annotation decisions.
        </p>
      </div>

      {/* Search + Filter */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by patient ID..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-9"
          />
        </div>
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {data && (
          <span className="text-sm text-muted-foreground">
            {data.total} patient{data.total !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Patient table */}
      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="px-4 py-3 text-left font-medium">Patient ID</th>
              <th className="px-4 py-3 text-left font-medium">Status</th>
              <th className="px-4 py-3 text-right font-medium">Notes</th>
              <th className="px-4 py-3 text-right font-medium">Reviewed</th>
              <th className="px-4 py-3 text-left font-medium">Last Updated</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  Loading...
                </td>
              </tr>
            ) : !data?.items.length ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  {search || status ? "No patients match your filters." : "No patients yet."}
                </td>
              </tr>
            ) : (
              data.items.map((patient) => (
                <tr
                  key={patient.id}
                  onClick={() =>
                    navigate(`/projects/${projectId}/patients/${patient.id}`)
                  }
                  className="cursor-pointer border-b transition-colors hover:bg-muted/50"
                >
                  <td className="px-4 py-3 font-medium">
                    {patient.patient_id_ext}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusBadgeVariant(patient.status)}>
                      {statusLabel(patient.status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {patient.note_count}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {patient.annotation_count > 0
                      ? `${patient.reviewed_count}/${patient.annotation_count}`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {new Date(patient.updated_at).toLocaleDateString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              <ChevronLeft className="mr-1 h-4 w-4" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage >= totalPages}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
              <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
