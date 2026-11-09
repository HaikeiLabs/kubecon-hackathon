// API client. Uses the FastAPI backend for endpoints that exist; triage and
// organizer assignment are mock-only until the backend adds them.
// Set VITE_USE_MOCK=true to run fully against the seeded mock store.
import { mock } from "./mock";
import { triage as localTriage } from "./triage";
import type { Assignment, Bucket, BucketSearchResult, Report, ReportSubmission, TriageResult } from "./types";

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { "content-type": "application/json", ...init?.headers } });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  submitReport: (sub: ReportSubmission) =>
    USE_MOCK ? mock.submitReport(sub) : http<Report>("/api/reports", { method: "POST", body: JSON.stringify(sub) }),

  listReports: () => (USE_MOCK ? mock.listReports() : http<Report[]>("/api/reports")),

  listBuckets: () => (USE_MOCK ? mock.listBuckets() : http<Bucket[]>("/api/buckets")),

  /** Until the backend returns a TriageResult, derive one from lexical bucket search. */
  async getTriage(report: Report, buckets: Bucket[], reports: Report[]): Promise<TriageResult | null> {
    if (USE_MOCK) return mock.getTriage(report.id);
    const q = report.description.slice(0, 500);
    const hits = await http<BucketSearchResult[]>(`/api/buckets/search?q=${encodeURIComponent(q)}&limit=5`);
    const candidates = hits.length ? hits.map((h) => h.bucket) : buckets;
    return localTriage(report, candidates, reports);
  },

  async assign(reportId: string, a: Assignment): Promise<Report> {
    if (USE_MOCK) return mock.assign(reportId, a);
    throw new ApiError("Confirming assignments isn't supported by the API yet. Run with VITE_USE_MOCK=true to demo this step.");
  },
};
