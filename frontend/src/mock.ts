// Seeded in-memory store persisted to localStorage, so the attendee page in one
// tab and the organizer page in another share state during a demo.
import { triage } from "./triage";
import type { Assignment, Bucket, Report, ReportSubmission, TriageResult } from "./types";

const KEY = "friction-desk-mock-v1";

interface Store {
  reports: Report[];
  buckets: Bucket[];
  triage: Record<string, TriageResult>;
}

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

function seed(): Store {
  const buckets: Bucket[] = [
    {
      id: "b-hallb",
      title: "Accessible entrance at Hall B blocked",
      summary: "Step-free entrance to Hall B is obstructed by equipment carts; wheelchair users are being rerouted outside.",
      status: "open",
      report_count: 2,
      updated_at: ago(25),
    },
    {
      id: "b-wifi",
      title: "Wi-Fi drops in Room 2A",
      summary: "Attendees lose the conference Wi-Fi during sessions in Room 2A; demos and live polls fail.",
      status: "open",
      report_count: 3,
      updated_at: ago(40),
    },
    {
      id: "b-app",
      title: "Schedule app shows wrong room for keynote",
      summary: "The mobile schedule lists the Day 2 keynote in Room 1 instead of the main stage.",
      status: "open",
      report_count: 1,
      updated_at: ago(90),
    },
  ];
  const confirmed: Report[] = [
    { id: "r1", description: "Couldn't get my wheelchair into Hall B, the ramp entrance is full of carts.", location: "Hall B", created_at: ago(60), status: "confirmed", bucket_id: "b-hallb" },
    { id: "r2", description: "Accessible entrance to Hall B blocked by equipment, had to go around outside.", location: "Hall B east door", created_at: ago(25), status: "confirmed", bucket_id: "b-hallb" },
    { id: "r3", description: "Wi-Fi keeps dropping during the talk in 2A.", location: "Room 2A", created_at: ago(120), status: "confirmed", bucket_id: "b-wifi" },
    { id: "r4", description: "Live poll wouldn't load, network disconnected repeatedly.", location: "Room 2A", created_at: ago(70), status: "confirmed", bucket_id: "b-wifi" },
    { id: "r5", description: "Speaker's demo failed because the wifi cut out.", location: "2A", created_at: ago(40), status: "confirmed", bucket_id: "b-wifi" },
    { id: "r6", description: "App says the keynote is in Room 1 but it's on the main stage.", location: null, created_at: ago(90), status: "confirmed", bucket_id: "b-app" },
  ];
  const incoming: Report[] = [
    { id: "r7", description: "Wi-Fi in room 2A disconnected three times during the session.", location: "Room 2A", created_at: ago(8), status: "proposed", bucket_id: null },
    { id: "r8", description: "No vegetarian options left at the lunch station by 12:15.", location: "Expo hall food court", created_at: ago(5), status: "proposed", bucket_id: null },
    { id: "r9", description: "The room schedule on the door doesn't match the app.", location: "Room 3C", created_at: ago(2), status: "proposed", bucket_id: null },
  ];
  const store: Store = { buckets, reports: [...incoming, ...confirmed], triage: {} };
  for (const r of incoming) store.triage[r.id] = triage(r, buckets, confirmed);
  return store;
}

function load(): Store {
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
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable: state lives for this page only */
  }
}

const delay = <T,>(v: T, ms = 350) => new Promise<T>((r) => setTimeout(() => r(v), ms));

export const mock = {
  async submitReport(sub: ReportSubmission): Promise<Report> {
    const s = load();
    const report: Report = {
      id: crypto.randomUUID(),
      description: sub.description.trim(),
      location: sub.location?.trim() || null,
      created_at: new Date().toISOString(),
      status: "proposed",
      bucket_id: null,
    };
    s.reports.unshift(report);
    s.triage[report.id] = triage(report, s.buckets, s.reports);
    save(s);
    return delay(report, 600);
  },
  async listReports(): Promise<Report[]> {
    return delay(load().reports);
  },
  async listBuckets(): Promise<Bucket[]> {
    return delay([...load().buckets].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
  },
  async getTriage(reportId: string): Promise<TriageResult | null> {
    return delay(load().triage[reportId] ?? null, 100);
  },
  async assign(reportId: string, a: Assignment): Promise<Report> {
    const s = load();
    const report = s.reports.find((r) => r.id === reportId);
    if (!report) throw new Error("Report not found");
    let bucket: Bucket | undefined;
    if (a.kind === "existing") {
      bucket = s.buckets.find((b) => b.id === a.bucket_id);
      if (!bucket) throw new Error("Issue not found");
      bucket.report_count += 1;
      bucket.updated_at = new Date().toISOString();
    } else {
      bucket = { id: `b-${crypto.randomUUID().slice(0, 8)}`, title: a.title, summary: a.summary, status: "open", report_count: 1, updated_at: new Date().toISOString() };
      s.buckets.push(bucket);
    }
    report.status = "confirmed";
    report.bucket_id = bucket.id;
    delete s.triage[reportId];
    save(s);
    return delay(report);
  },
  reset() {
    save(seed());
  },
  storageKey: KEY,
};
