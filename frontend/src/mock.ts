// Seeded in-memory store persisted to localStorage, so the attendee page in one
// tab and the organizer page in another share state during a demo. Implements
// the same contract as the backend API (including the X-Role governance check).
import { linkConcepts, topConceptLabel, triage } from "./triage";
import type { Bucket, ConfirmRequest, GovernanceEvent, Report, ReportSubmission, Role } from "./types";

const KEY = "friction-desk-mock-v2";

interface Store {
  reports: Report[];
  buckets: Bucket[];
  audit: GovernanceEvent[];
}

export class MockHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

function bucket(id: string, title: string, summary: string, report_count: number, updatedMin: number, concept_ids: string[]): Bucket {
  return {
    id,
    title,
    summary,
    status: "open",
    report_count,
    updated_at: ago(updatedMin),
    concept_ids,
    concept_ancestors: [],
    category: topConceptLabel(concept_ids[0]),
  };
}

function report(id: string, description: string, location: string | null, min: number, bucket_id: string | null): Report {
  return {
    id,
    description,
    location,
    created_at: ago(min),
    status: bucket_id ? "confirmed" : "proposed",
    bucket_id,
    ...linkConcepts(`${description} ${location ?? ""}`),
    triage: null,
  };
}

function seed(): Store {
  const buckets: Bucket[] = [
    bucket("b-hallb", "Accessible entrance at Hall B blocked", "Step-free entrance to Hall B is obstructed by equipment carts; wheelchair users are being rerouted outside.", 2, 25, ["fd:StepFreeAccess", "fd:BlockedEntrance"]),
    bucket("b-wifi", "Wi-Fi drops in Room 2A", "Attendees lose the conference Wi-Fi during sessions in Room 2A; demos and live polls fail.", 3, 40, ["fd:WifiOutage"]),
    bucket("b-app", "Schedule app shows wrong room for keynote", "The mobile schedule lists the Day 2 keynote in Room 1 instead of the main stage.", 1, 90, ["fd:ScheduleMismatch", "fd:EventApp"]),
  ];
  const confirmed: Report[] = [
    report("r1", "Couldn't get my wheelchair into Hall B, the ramp entrance is full of carts.", "Hall B", 60, "b-hallb"),
    report("r2", "Accessible entrance to Hall B blocked by equipment, had to go around outside.", "Hall B east door", 25, "b-hallb"),
    report("r3", "Wi-Fi keeps dropping during the talk in 2A.", "Room 2A", 120, "b-wifi"),
    report("r4", "Live poll wouldn't load, network disconnected repeatedly.", "Room 2A", 70, "b-wifi"),
    report("r5", "Speaker's demo failed because the wifi cut out.", "2A", 40, "b-wifi"),
    report("r6", "App says the keynote is in Room 1 but it's on the main stage.", null, 90, "b-app"),
  ];
  const incoming: Report[] = [
    report("r7", "Wi-Fi in room 2A disconnected three times during the session.", "Room 2A", 8, null),
    report("r8", "No vegetarian options left at the lunch station by 12:15.", "Expo hall food court", 5, null),
    report("r9", "The room schedule on the door doesn't match the app.", "Room 3C", 2, null),
  ];
  const audit: GovernanceEvent[] = [];
  for (const r of incoming) {
    r.triage = triage(r, buckets, confirmed);
    audit.push(...r.triage.governance);
  }
  return { buckets, reports: [...incoming, ...confirmed], audit };
}

// Fallback when localStorage is unavailable (private mode, tests).
let memory: Store | null = null;

function load(): Store {
  if (memory) return memory;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Store;
  } catch {
    /* fall through to seed */
  }
  const s = seed();
  save(s);
  return s;
}

function save(s: Store) {
  s.audit = s.audit.slice(-200);
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    memory = s; // storage unavailable: state lives for this page only
  }
}

const delay = <T,>(v: T, ms = 350) => new Promise<T>((r) => setTimeout(() => r(v), ms));

function find(s: Store, id: string): Report {
  const r = s.reports.find((x) => x.id === id);
  if (!r) throw new MockHttpError("Report not found", 404);
  return r;
}

export const mock = {
  async submitReport(sub: ReportSubmission): Promise<Report> {
    const s = load();
    const r = report(crypto.randomUUID(), sub.description.trim(), sub.location?.trim() || null, 0, null);
    r.triage = triage(r, s.buckets, s.reports);
    s.audit.push(...r.triage.governance);
    s.reports.unshift(r);
    save(s);
    return delay(r, 600);
  },
  async listReports(): Promise<Report[]> {
    return delay(load().reports);
  },
  async listBuckets(): Promise<Bucket[]> {
    return delay([...load().buckets].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
  },
  async triageReport(id: string): Promise<Report> {
    const s = load();
    const r = find(s, id);
    r.triage = triage(r, s.buckets, s.reports.filter((x) => x.status === "confirmed"));
    r.status = "proposed";
    s.audit.push(...r.triage.governance);
    save(s);
    return delay(r);
  },
  async confirm(id: string, req: ConfirmRequest, role: Role): Promise<Report> {
    const s = load();
    const r = find(s, id);
    const at = new Date().toISOString();
    if (role !== "organizer") {
      s.audit.push({ tool: "friction.assign_report", decision: "deny", rule: "assign-requires-organizer", reason: `Role "${role}" may not assign reports; organizer confirmation required.`, at });
      save(s);
      throw new MockHttpError("Denied by policy: only an organizer can assign reports to buckets.", 403);
    }
    let b: Bucket | undefined;
    if (req.bucket_id) {
      b = s.buckets.find((x) => x.id === req.bucket_id);
      if (!b) throw new MockHttpError("Bucket not found", 404);
      b.report_count += 1;
      b.updated_at = at;
    } else {
      b = {
        id: `b-${crypto.randomUUID().slice(0, 8)}`,
        title: req.new_bucket_title!,
        summary: req.new_bucket_summary ?? "",
        status: "open",
        report_count: 1,
        updated_at: at,
        concept_ids: r.concept_ids,
        concept_ancestors: r.concept_ancestors,
        category: topConceptLabel(r.concept_ids[0]),
      };
      s.buckets.push(b);
    }
    s.audit.push({ tool: "friction.assign_report", decision: "allow", rule: "organizer-may-assign", reason: "Organizer confirmed the assignment.", at });
    r.status = "confirmed";
    r.bucket_id = b.id;
    save(s);
    return delay(r);
  },
  async listAudit(limit: number): Promise<GovernanceEvent[]> {
    return delay(load().audit.slice(-limit).reverse(), 100);
  },
  async reset(): Promise<void> {
    save(seed());
    return delay(undefined);
  },
  storageKey: KEY,
};
