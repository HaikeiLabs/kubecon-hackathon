import { useCallback, useEffect, useMemo, useState } from "react";
import { api, USE_MOCK } from "./api";
import { mock } from "./mock";
import { HIGH_CONFIDENCE } from "./triage";
import type { Assignment, Bucket, Report, TriageResult } from "./types";

type Load = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready" };

function timeAgo(iso: string) {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : new Date(iso).toLocaleDateString();
}

export default function OrganizerPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [triage, setTriage] = useState<Record<string, TriageResult | null | "error">>({});
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [rs, bs] = await Promise.all([api.listReports(), api.listBuckets()]);
      setReports(rs);
      setBuckets(bs);
      setLoad({ kind: "ready" });
      setRefreshedAt(new Date());
      const pending = rs.filter((r) => r.status !== "confirmed");
      const entries = await Promise.all(
        pending.map(async (r) => [r.id, await api.getTriage(r, bs, rs).catch(() => "error" as const)] as const),
      );
      setTriage(Object.fromEntries(entries));
    } catch (err) {
      setLoad({ kind: "error", message: err instanceof Error ? err.message : "Couldn't load reports." });
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15_000);
    // In mock mode, pick up reports submitted from another tab immediately.
    const onStorage = (e: StorageEvent) => e.key === mock.storageKey && refresh();
    addEventListener("storage", onStorage);
    return () => {
      clearInterval(t);
      removeEventListener("storage", onStorage);
    };
  }, [refresh]);

  const inbox = useMemo(() => reports.filter((r) => r.status !== "confirmed"), [reports]);
  const bucketById = useMemo(() => new Map(buckets.map((b) => [b.id, b])), [buckets]);

  async function assign(report: Report, a: Assignment) {
    await api.assign(report.id, a);
    const name = a.kind === "existing" ? bucketById.get(a.bucket_id)?.title : a.title;
    setAnnounce(`Report filed under “${name}”.`);
    await refresh();
  }

  return (
    <div className="organizer">
      <div className="page-head">
        <div>
          <h1>Organizer inbox</h1>
          <p className="muted">
            {refreshedAt ? `Updated ${refreshedAt.toLocaleTimeString()}` : "Loading…"} · refreshes every 15 s
          </p>
        </div>
        <div className="actions">
          <button onClick={refresh}>Refresh</button>
          {USE_MOCK && (
            <button onClick={() => { mock.reset(); setSelected(null); refresh(); }}>Reset demo data</button>
          )}
        </div>
      </div>
      <div className="sr-only" aria-live="polite">{announce}</div>

      {load.kind === "error" && (
        <div className="alert" role="alert">
          <strong>Couldn't load the inbox.</strong> {load.message} <button onClick={refresh}>Try again</button>
        </div>
      )}

      <div className="columns">
        <section aria-labelledby="inbox-h">
          <h2 id="inbox-h">Needs review <span className="count">{inbox.length}</span></h2>
          {load.kind === "loading" && <p className="muted">Loading reports…</p>}
          {load.kind === "ready" && inbox.length === 0 && <p className="empty">All caught up — no reports waiting for review.</p>}
          <ul className="stack">
            {inbox.map((r) => (
              <li key={r.id}>
                <InboxCard report={r} triage={triage[r.id]} buckets={buckets} bucketById={bucketById} onAssign={(a) => assign(r, a)} onOpenBucket={setSelected} />
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="issues-h">
          <h2 id="issues-h">Issues <span className="count">{buckets.length}</span></h2>
          {load.kind === "ready" && buckets.length === 0 && <p className="empty">No issues yet. Confirming a report creates one.</p>}
          <ul className="stack">
            {buckets.map((b) => (
              <li key={b.id}>
                <BucketCard bucket={b} open={selected === b.id} onToggle={() => setSelected(selected === b.id ? null : b.id)} reports={reports.filter((r) => r.bucket_id === b.id)} />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function InboxCard(props: {
  report: Report;
  triage: TriageResult | null | "error" | undefined;
  buckets: Bucket[];
  bucketById: Map<string, Bucket>;
  onAssign: (a: Assignment) => Promise<void>;
  onOpenBucket: (id: string) => void;
}) {
  const { report, triage, buckets, bucketById } = props;
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(a: Assignment) {
    setBusy(true);
    setError(null);
    try {
      await props.onAssign(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save.");
      setBusy(false);
    }
  }

  const proposal: Assignment | null =
    triage && triage !== "error"
      ? triage.kind === "existing"
        ? { kind: "existing", bucket_id: triage.bucket_id }
        : { kind: "new", title: triage.proposed_title, summary: triage.proposed_summary }
      : null;
  const lowConfidence = triage && triage !== "error" && triage.confidence < HIGH_CONFIDENCE;

  return (
    <article className="card inbox-card" aria-label={`Report from ${timeAgo(report.created_at)}`}>
      <div className="attendee">
        <div className="label">Attendee report · {timeAgo(report.created_at)}</div>
        <blockquote>{report.description}</blockquote>
        {report.location && <div className="meta">📍 {report.location}</div>}
      </div>

      <div className="ai" aria-label="AI suggestion">
        <div className="label">
          AI suggestion
          {triage && triage !== "error" && (
            <span className={`pill ${triage.kind}`}>{triage.kind === "existing" ? "Add to existing issue" : "New issue"}</span>
          )}
        </div>
        {triage === undefined && <p className="muted">Analyzing…</p>}
        {triage === null && <p className="muted">No suggestion yet. Choose an issue manually.</p>}
        {triage === "error" && <p className="warn">The triage agent couldn't process this report. Choose an issue manually.</p>}
        {triage && triage !== "error" && (
          <>
            {triage.kind === "existing" ? (
              <p className="proposal">
                <button className="link" onClick={() => props.onOpenBucket(triage.bucket_id)}>{bucketById.get(triage.bucket_id)?.title ?? "Unknown issue"}</button>
                <span className="muted"> · {bucketById.get(triage.bucket_id)?.report_count ?? 0} related reports</span>
              </p>
            ) : (
              <p className="proposal"><strong>{triage.proposed_title}</strong></p>
            )}
            <p>{triage.explanation}</p>
            <p className="muted">Next step: {triage.suggested_action}</p>
            <Confidence value={triage.confidence} />
            {lowConfidence && <p className="warn">Low confidence — please confirm or correct.</p>}
          </>
        )}
      </div>

      {error && <div className="alert" role="alert">{error}</div>}

      {editing ? (
        <CorrectionForm buckets={buckets} initial={proposal} busy={busy} onCancel={() => setEditing(false)} onSave={run} />
      ) : (
        <div className="actions">
          {proposal && (
            <button className="primary" disabled={busy} onClick={() => run(proposal)}>
              {busy ? "Saving…" : proposal.kind === "existing" ? "Confirm match" : "Create issue"}
            </button>
          )}
          <button disabled={busy} onClick={() => setEditing(true)}>{proposal ? "Change…" : "Choose issue…"}</button>
        </div>
      )}
    </article>
  );
}

function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const level = value >= HIGH_CONFIDENCE ? "high" : value >= 0.4 ? "medium" : "low";
  return (
    <div className="confidence">
      <span>Confidence: {level} ({pct}%)</span>
      <span className={`bar ${level}`} aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
    </div>
  );
}

function CorrectionForm(props: { buckets: Bucket[]; initial: Assignment | null; busy: boolean; onCancel: () => void; onSave: (a: Assignment) => void }) {
  const open = props.buckets.filter((b) => b.status === "open");
  const [mode, setMode] = useState<"existing" | "new">(props.initial?.kind ?? (open.length ? "existing" : "new"));
  const [bucketId, setBucketId] = useState(props.initial?.kind === "existing" ? props.initial.bucket_id : open[0]?.id ?? "");
  const [title, setTitle] = useState(props.initial?.kind === "new" ? props.initial.title : "");
  const [summary, setSummary] = useState(props.initial?.kind === "new" ? props.initial.summary : "");
  const valid = mode === "existing" ? !!bucketId : title.trim().length > 2;

  return (
    <form
      className="correction"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) props.onSave(mode === "existing" ? { kind: "existing", bucket_id: bucketId } : { kind: "new", title: title.trim(), summary: summary.trim() });
      }}
    >
      <fieldset>
        <legend>File this report under</legend>
        <label className="radio"><input type="radio" name="mode" checked={mode === "existing"} onChange={() => setMode("existing")} disabled={!open.length} /> An existing issue</label>
        <label className="radio"><input type="radio" name="mode" checked={mode === "new"} onChange={() => setMode("new")} /> A new issue</label>
      </fieldset>
      {mode === "existing" ? (
        <div className="field">
          <label htmlFor="bucket-select">Issue</label>
          <select id="bucket-select" value={bucketId} onChange={(e) => setBucketId(e.target.value)}>
            {open.map((b) => <option key={b.id} value={b.id}>{b.title} ({b.report_count})</option>)}
          </select>
        </div>
      ) : (
        <>
          <div className="field">
            <label htmlFor="new-title">Title</label>
            <input id="new-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} />
          </div>
          <div className="field">
            <label htmlFor="new-summary">Summary</label>
            <textarea id="new-summary" rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </div>
        </>
      )}
      <div className="actions">
        <button className="primary" type="submit" disabled={!valid || props.busy}>{props.busy ? "Saving…" : "Save"}</button>
        <button type="button" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
      </div>
    </form>
  );
}

function BucketCard({ bucket, reports, open, onToggle }: { bucket: Bucket; reports: Report[]; open: boolean; onToggle: () => void }) {
  const locations = [...new Set(reports.map((r) => r.location).filter(Boolean))];
  const latest = reports.reduce<string | null>((m, r) => (!m || r.created_at > m ? r.created_at : m), null);
  return (
    <article className={`card bucket-card ${open ? "open" : ""}`}>
      <button className="bucket-head" aria-expanded={open} aria-controls={`bucket-${bucket.id}`} onClick={onToggle}>
        <span className="bucket-title">{bucket.title}</span>
        <span className="muted">{bucket.report_count} report{bucket.report_count === 1 ? "" : "s"} · {timeAgo(bucket.updated_at)}</span>
        {bucket.status === "resolved" && <span className="pill">Resolved</span>}
      </button>
      {open && (
        <div id={`bucket-${bucket.id}`} className="bucket-detail">
          <p>{bucket.summary}</p>
          <div className="impact">
            <div className="label">Impact</div>
            <p>
              {bucket.report_count} report{bucket.report_count === 1 ? "" : "s"}
              {latest && `, most recent ${timeAgo(latest)}`}
              {locations.length > 0 && ` · ${locations.join(", ")}`}
            </p>
          </div>
          <div className="label">Attendee reports</div>
          {reports.length === 0 ? (
            <p className="muted">No reports loaded for this issue.</p>
          ) : (
            <ul className="reports">
              {reports.map((r) => (
                <li key={r.id}><blockquote>{r.description}</blockquote><span className="muted">{r.location ? `${r.location} · ` : ""}{timeAgo(r.created_at)}</span></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}
