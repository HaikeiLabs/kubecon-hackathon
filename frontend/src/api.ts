// API client. Talks to the FastAPI backend when VITE_API_BASE is set (use "/"
// with the vite dev proxy, or an absolute URL); otherwise runs fully on the
// seeded mock store. VITE_USE_MOCK=true forces mock mode.
import { mock, MockHttpError } from "./mock";
import type { Bucket, ConfirmRequest, GovernanceEvent, Report, ReportSubmission, Role } from "./types";

const RAW_BASE = import.meta.env.VITE_API_BASE as string | undefined;
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true" || RAW_BASE === undefined;
const BASE = (RAW_BASE ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
  }
}

const ROLE_KEY = "friction-desk-role";
let role: Role = "organizer";
try {
  if (localStorage.getItem(ROLE_KEY) === "attendee-agent") role = "attendee-agent";
} catch {
  /* storage unavailable */
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; ");
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    for (const k of ["message", "reason", "detail"]) if (typeof d[k] === "string") return d[k] as string;
  }
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
    let msg = `Request failed (${res.status})`;
    try {
      msg = detailMessage((await res.json()).detail) ?? msg;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status === 403 ? `Denied by policy: ${msg}` : msg, res.status);
  }
  return res.json() as Promise<T>;
}

/** Runs a mock call, mapping mock HTTP errors onto ApiError like the real client. */
async function viaMock<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof MockHttpError) throw new ApiError(e.message, e.status);
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

  async listAudit(limit = 25): Promise<GovernanceEvent[]> {
    if (USE_MOCK) return mock.listAudit(limit);
    const body = await http<GovernanceEvent[] | { events: GovernanceEvent[] }>(`/api/audit?limit=${limit}`);
    const events = Array.isArray(body) ? body : body.events ?? [];
    return [...events].sort((a, b) => b.at.localeCompare(a.at));
  },

  resetDemo: () => (USE_MOCK ? mock.reset() : http<unknown>("/api/admin/reset", { method: "POST" }).then(() => undefined)),
};
