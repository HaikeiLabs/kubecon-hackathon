// API client. Talks to the FastAPI backend when VITE_API_BASE is set (use "/"
// with the vite dev proxy, or an absolute URL); otherwise runs fully on the
// seeded mock store. VITE_USE_MOCK=true forces mock mode.
import { mock, MockHttpError } from "./mock";
import type { Bucket, ConfirmRequest, GovernanceEvent, Report, ReportSubmission, Role } from "./types";

const RAW_BASE = import.meta.env.VITE_API_BASE as string | undefined;
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true" || RAW_BASE === undefined;
const BASE = (RAW_BASE ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  /** Set when the backend's policy evaluator denied the call (403). */
  readonly governance?: GovernanceEvent;
  constructor(message: string, readonly status?: number, detail?: unknown) {
    super(message);
    this.governance = governanceFrom(detail);
  }
}

function governanceFrom(detail: unknown): GovernanceEvent | undefined {
  const g = detail && typeof detail === "object" ? (detail as { governance?: unknown }).governance : undefined;
  return g && typeof g === "object" && "rule" in g ? (g as GovernanceEvent) : undefined;
}

const ROLE_KEY = "friction-desk-role";
let role: Role = "organizer";
try {
  if (localStorage.getItem(ROLE_KEY) === "attendee-agent") role = "attendee-agent";
} catch {
  /* storage unavailable */
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail; // e.g. 503 "could not assign report"
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; "); // 422
  const g = governanceFrom(detail);
  if (g) return `Denied by policy (${g.rule}): ${g.reason}`;
  return null;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { "content-type": "application/json", "X-Role": role, ...init?.headers },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error */
    }
    const fallback = res.status === 403 ? "Denied by policy." : res.status === 422 ? "The request was invalid." : `Request failed (${res.status})`;
    throw new ApiError(detailMessage(detail) ?? fallback, res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** Runs a mock call, mapping mock HTTP errors onto ApiError like the real client. */
async function viaMock<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof MockHttpError) throw new ApiError(detailMessage(e.detail) ?? e.message, e.status, e.detail);
    throw e;
  }
}

export const api = {
  getRole: () => role,
  setRole(next: Role) {
    role = next;
    try {
      localStorage.setItem(ROLE_KEY, next);
    } catch {
      /* storage unavailable */
    }
  },

  submitReport: (sub: ReportSubmission) =>
    USE_MOCK ? mock.submitReport(sub) : http<Report>("/api/reports", { method: "POST", body: JSON.stringify(sub) }),

  listReports: () => (USE_MOCK ? mock.listReports() : http<Report[]>("/api/reports")),

  listBuckets: () => (USE_MOCK ? mock.listBuckets() : http<Bucket[]>("/api/buckets")),

  /** Re-run the triage agent for a report (fills report.triage). */
  triageReport: (id: string) =>
    USE_MOCK ? viaMock(() => mock.triageReport(id)) : http<Report>(`/api/reports/${encodeURIComponent(id)}/triage`, { method: "POST" }),

  /** Organizer confirmation. Sends X-Role; non-organizers get a governance deny (403). */
  confirm: (id: string, req: ConfirmRequest) =>
    USE_MOCK
      ? viaMock(() => mock.confirm(id, req, role))
      : http<Report>(`/api/reports/${encodeURIComponent(id)}/confirm`, { method: "POST", body: JSON.stringify(req) }),

  /** Newest first, as returned by the backend. */
  listAudit: (limit = 25) =>
    USE_MOCK ? mock.listAudit(limit) : http<GovernanceEvent[]>(`/api/audit?limit=${limit}`),

  resetDemo: () => (USE_MOCK ? mock.reset() : http<unknown>("/api/admin/reset", { method: "POST" }).then(() => undefined)),
};
