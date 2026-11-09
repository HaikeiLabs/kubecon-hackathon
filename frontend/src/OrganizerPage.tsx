import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { mock } from "./mock";
import { HIGH_CONFIDENCE } from "./triage";
import type { Bucket, ConceptTag, ConfirmRequest, GovernanceEvent, Report, Role, TriageResult } from "./types";

type Load = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready" };

function timeAgo(iso: string) {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : new Date(iso).toLocaleDateString();
}

const errMsg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export default function OrganizerPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [audit, setAudit] = useState<GovernanceEvent[]>([]);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const [role, setRoleState] = useState<Role>(api.getRole());
  const [resetting, setResetting] = useState(false);

  const refreshAudit = useCallback(async () => {
    try {
      setAudit(await api.listAudit(25));
    } catch {
      /* governance panel is best-effort */
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [rs, bs] = await Promise.all([api.listReports(), api.listBuckets()]);
      setReports(rs);
      setBuckets(bs);
      setLoad({ kind: "ready" });
      setRefreshedAt(new Date());
    } catch (err) {
      setLoad({ kind: "error", message: errMsg(err, "Couldn't load reports.") });
    }
    await refreshAudit();
  }, [refreshAudit]);

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

  async function confirm(report: Report, req: ConfirmRequest) {
    try {
      await api.confirm(report.id, req);
      const name = req.bucket_id ? bucketById.get(req.bucket_id)?.title : req.new_bucket_title;
      setAnnounce(`Report filed under “${name}”.`);
      await refresh();
    } catch (err) {
      // A 403 is a governance deny; show it in the audit panel too.
      if (err instanceof ApiError && err.status === 403) setAnnounce(err.message);
      await refreshAudit();
      throw err;
    }
  }

  async function retriage(report: Report) {
    await api.triageReport(report.id);
    setAnnounce("Triage finished.");
    await refresh();
  }

  async function reset() {
    setResetting(true);
    try {
      await api.resetDemo();
      setSelected(null);
      setAnnounce("Demo data reset.");
      await refresh();
    } catch (err) {
      setAnnounce(`Reset failed: ${errMsg(err, "unknown error")}`);
    } finally {
      setResetting(false);
    }
  }

  function changeRole(next: Role) {
    api.setRole(next);
    setRoleState(next);
    setAnnounce(next === "organizer" ? "Acting as organizer." : "Acting as attendee agent. Confirmations will be denied by policy.");
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
          <button onClick={reset} disabled={resetting} aria-busy={resetting}>{resetting ? "Resetting…" : "Reset demo data"}</button>
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
                <InboxCard
                  report={r}
                  buckets={buckets}
                  bucketById={bucketById}
                  onConfirm={(req) => confirm(r, req)}
                  onRetriage={() => retriage(r)}
                  onOpenBucket={setSelected}
                />
              </li>
            ))}
          </ul>
        </section>

        <div className="side">
          <BucketPanel buckets={buckets} reports={reports} selected={selected} onSelect={setSelected} ready={load.kind === "ready"} />
          <GovernancePanel events={audit} role={role} onRole={changeRole} />
        </div>
      </div>
    </div>
  );
}

function ConceptChips({ tags }: { tags: ConceptTag[] }) {
  if (!tags.length) return <p className="muted">No ontology concepts linked.</p>;
  return (
    <ul className="chips" aria-label="Ontology concepts">
      {tags.map((t) => {
        const detail = `${t.concept_id} · ${t.method} · ${Math.round(t.confidence * 100)}%`;
        return (
          <li key={t.concept_id}>
            <span className="chip" tabIndex={0} title={detail} data-tip={detail} aria-label={`${t.label} (${detail})`}>
              {t.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

type Editing = null | "existing" | "new";

function InboxCard(props: {
  report: Report;
  buckets: Bucket[];
  bucketById: Map<string, Bucket>;
  onConfirm: (req: ConfirmRequest) => Promise<void>;
  onRetriage: () => Promise<void>;
  onOpenBucket: (id: string) => void;
}) {
  const { report, buckets, bucketById } = props;
  const triage = report.triage;
  const [editing, setEditing] = useState<Editing>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errMsg(err, "Couldn't save."));
    } finally {
      setBusy(false);
    }
  }

  const proposal: ConfirmRequest | null = !triage
    ? null
    : triage.disposition === "existing_bucket" && triage.bucket_id
      ? { bucket_id: triage.bucket_id }
      : triage.disposition === "new_bucket" && triage.proposed_title
        ? { new_bucket_title: triage.proposed_title, new_bucket_summary: triage.proposed_summary ?? "" }
        : null;
  const needsReview = triage?.disposition === "needs_review";

  return (
    <article className={`card inbox-card ${needsReview ? "needs-review" : ""}`} aria-label={`Report from ${timeAgo(report.created_at)}`}>
      {needsReview && <div className="review-flag" role="status">⚑ Needs organizer review</div>}
      <div className="attendee">
        <div className="label">Attendee-provided report · {timeAgo(report.created_at)}</div>
        <blockquote>{report.description}</blockquote>
        {report.location && <div className="meta"><span aria-hidden="true">📍 </span>Location: {report.location}</div>}
        <div className="label concepts-label">Ontology concepts</div>
        <ConceptChips tags={report.concept_tags ?? []} />
      </div>

      {triage ? (
        <Proposal triage={triage} bucketById={bucketById} onOpenBucket={props.onOpenBucket} onPick={(id) => run(() => props.onConfirm({ bucket_id: id }))} busy={busy} />
      ) : (
        <div className="ai" aria-label="AI suggestion">
          <div className="label">AI-generated suggestion</div>
          <p className="muted">Not triaged yet.</p>
          <button disabled={busy} onClick={() => run(props.onRetriage)}>{busy ? "Running triage…" : "Run triage"}</button>
        </div>
      )}

      <div aria-live="assertive">{error && <div className="alert" role="alert">{error}</div>}</div>

      {editing ? (
        <CorrectionForm
          buckets={buckets}
          mode={editing}
          initial={proposal}
          busy={busy}
          onCancel={() => setEditing(null)}
          onSave={(req) => run(() => props.onConfirm(req))}
        />
      ) : (
        <div className="actions">
          {proposal && (
            <button className="primary" disabled={busy} onClick={() => run(() => props.onConfirm(proposal))}>
              {busy ? "Saving…" : proposal.bucket_id ? "Confirm match" : "Confirm new bucket"}
            </button>
          )}
          <button disabled={busy} onClick={() => setEditing("existing")}>Pick another bucket…</button>
          <button disabled={busy} onClick={() => setEditing("new")}>Create new…</button>
        </div>
      )}
    </article>
  );
}

function Proposal(props: {
  triage: TriageResult;
  bucketById: Map<string, Bucket>;
  onOpenBucket: (id: string) => void;
  onPick: (bucketId: string) => void;
  busy: boolean;
}) {
  const { triage, bucketById } = props;
  const existing = triage.disposition === "existing_bucket" && triage.bucket_id ? bucketById.get(triage.bucket_id) : undefined;
  const pill =
    triage.disposition === "existing_bucket"
      ? { cls: "existing", text: "Existing bucket" }
      : triage.disposition === "new_bucket"
        ? { cls: "new", text: "Proposed NEW bucket" }
        : { cls: "review", text: "No confident match" };

  return (
    <div className={`ai proposal-${pill.cls}`} aria-label="AI-generated suggestion">
      <div className="label">
        AI-generated suggestion
        <span className={`pill ${pill.cls}`}>{pill.text}</span>
      </div>
      {triage.disposition === "existing_bucket" && triage.bucket_id && (
        <p className="proposal">
          <button className="link" onClick={() => props.onOpenBucket(triage.bucket_id!)}>{existing?.title ?? "Unknown bucket"}</button>
          <span className="muted"> ({plural(existing?.report_count ?? 0, "report")})</span>
        </p>
      )}
      {triage.disposition === "new_bucket" && (
        <div className="proposal new-bucket">
          <strong>NEW: {triage.proposed_title}</strong>
          {triage.proposed_summary && <p className="muted">{triage.proposed_summary}</p>}
        </div>
      )}
      <p><span className="sr-only">Rationale: </span>{triage.rationale}</p>
      <Confidence value={triage.confidence} />

      {triage.candidates.length > 0 && (
        <details className="candidates" open={triage.disposition === "needs_review"}>
          <summary>Candidate buckets ({triage.candidates.length})</summary>
          <ul>
            {triage.candidates.map((c) => (
              <li key={c.bucket.id}>
                <span>
                  {c.bucket.title} <span className="muted">· score {c.score.toFixed(2)} · {plural(c.bucket.report_count, "report")}</span>
                </span>
                <button disabled={props.busy} onClick={() => props.onPick(c.bucket.id)} aria-label={`File under ${c.bucket.title}`}>Use</button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="muted small">Extractor {triage.extractor_version}</p>
    </div>
  );
}

function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const level = value >= HIGH_CONFIDENCE ? "high" : value >= 0.4 ? "medium" : "low";
  return (
    <div className="confidence">
      <span>Confidence: {level} ({pct}%)</span>
      <span className={`bar ${level}`} role="meter" aria-label="AI confidence" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <span style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

function CorrectionForm(props: {
  buckets: Bucket[];
  mode: "existing" | "new";
  initial: ConfirmRequest | null;
  busy: boolean;
  onCancel: () => void;
  onSave: (req: ConfirmRequest) => void;
}) {
  const open = props.buckets.filter((b) => b.status === "open");
  const [mode, setMode] = useState<"existing" | "new">(props.mode === "existing" && !open.length ? "new" : props.mode);
  const [bucketId, setBucketId] = useState(props.initial?.bucket_id ?? open[0]?.id ?? "");
  const [title, setTitle] = useState(props.initial?.new_bucket_title ?? "");
  const [summary, setSummary] = useState(props.initial?.new_bucket_summary ?? "");
  const valid = mode === "existing" ? !!bucketId : title.trim().length > 2;
  const uid = useMemo(() => Math.random().toString(36).slice(2, 8), []);

  return (
    <form
      className="correction"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) props.onSave(mode === "existing" ? { bucket_id: bucketId } : { new_bucket_title: title.trim(), new_bucket_summary: summary.trim() });
      }}
    >
      <fieldset>
        <legend>File this report under</legend>
        <label className="radio"><input type="radio" name={`mode-${uid}`} checked={mode === "existing"} onChange={() => setMode("existing")} disabled={!open.length} /> An existing bucket</label>
        <label className="radio"><input type="radio" name={`mode-${uid}`} checked={mode === "new"} onChange={() => setMode("new")} /> A new bucket</label>
      </fieldset>
      {mode === "existing" ? (
        <div className="field">
          <label htmlFor={`bucket-${uid}`}>Bucket</label>
          <select id={`bucket-${uid}`} value={bucketId} onChange={(e) => setBucketId(e.target.value)} autoFocus>
            {open.map((b) => <option key={b.id} value={b.id}>{b.category ? `[${b.category}] ` : ""}{b.title} ({b.report_count})</option>)}
          </select>
        </div>
      ) : (
        <>
          <div className="field">
            <label htmlFor={`title-${uid}`}>Title</label>
            <input id={`title-${uid}`} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} autoFocus />
          </div>
          <div className="field">
            <label htmlFor={`summary-${uid}`}>Summary</label>
            <textarea id={`summary-${uid}`} rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </div>
        </>
      )}
      <div className="actions">
        <button className="primary" type="submit" disabled={!valid || props.busy}>{props.busy ? "Saving…" : "Confirm"}</button>
        <button type="button" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
      </div>
    </form>
  );
}

function BucketPanel(props: { buckets: Bucket[]; reports: Report[]; selected: string | null; onSelect: (id: string | null) => void; ready: boolean }) {
  const groups = useMemo(() => {
    const m = new Map<string, Bucket[]>();
    for (const b of props.buckets) {
      const k = b.category ?? "Uncategorized";
      m.set(k, [...(m.get(k) ?? []), b]);
    }
    return [...m.entries()]
      .map(([category, bs]) => ({ category, buckets: bs, total: bs.reduce((n, b) => n + b.report_count, 0) }))
      .sort((a, b) => b.total - a.total);
  }, [props.buckets]);

  return (
    <section aria-labelledby="issues-h">
      <h2 id="issues-h">Buckets <span className="count">{props.buckets.length}</span></h2>
      {props.ready && props.buckets.length === 0 && <p className="empty">No buckets yet. Confirming a report creates one.</p>}
      {groups.map((g) => (
        <div key={g.category} className="category">
          <h3>{g.category} <span className="muted">· {plural(g.total, "report")}</span></h3>
          <ul className="stack">
            {g.buckets.map((b) => (
              <li key={b.id}>
                <BucketCard
                  bucket={b}
                  open={props.selected === b.id}
                  onToggle={() => props.onSelect(props.selected === b.id ? null : b.id)}
                  reports={props.reports.filter((r) => r.bucket_id === b.id)}
                />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

function GovernancePanel({ events, role, onRole }: { events: GovernanceEvent[]; role: Role; onRole: (r: Role) => void }) {
  return (
    <section aria-labelledby="gov-h" className="governance">
      <h2 id="gov-h">Governance <span className="count">{events.length}</span></h2>
      <fieldset className="role-toggle">
        <legend>Act as (sent as X-Role)</legend>
        <label className="radio"><input type="radio" name="role" checked={role === "organizer"} onChange={() => onRole("organizer")} /> Organizer</label>
        <label className="radio"><input type="radio" name="role" checked={role === "attendee-agent"} onChange={() => onRole("attendee-agent")} /> Attendee agent</label>
      </fieldset>
      {role !== "organizer" && <p className="warn">Confirming as the attendee agent will be denied by policy.</p>}
      {events.length === 0 ? (
        <p className="muted">No agent tool calls recorded yet.</p>
      ) : (
        <ul className="audit" aria-label="Recent tool-call decisions">
          {events.map((e, i) => (
            <li key={`${e.at}-${e.tool}-${i}`} className={e.decision}>
              <span className={`decision ${e.decision}`}>{e.decision === "allow" ? "✓ allow" : "✕ deny"}</span>
              <code>{e.tool}</code>
              <span className="muted"> · rule {e.rule} · {timeAgo(e.at)}</span>
              <div className="reason">{e.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BucketCard({ bucket, reports, open, onToggle }: { bucket: Bucket; reports: Report[]; open: boolean; onToggle: () => void }) {
  const locations = [...new Set(reports.map((r) => r.location).filter(Boolean))];
  const latest = reports.reduce<string | null>((m, r) => (!m || r.created_at > m ? r.created_at : m), null);
  return (
    <article className={`card bucket-card ${open ? "open" : ""}`}>
      <button className="bucket-head" aria-expanded={open} aria-controls={`bucket-${bucket.id}`} onClick={onToggle}>
        <span className="bucket-title">{bucket.title}</span>
        <span className="muted">{plural(bucket.report_count, "report")} · {timeAgo(bucket.updated_at)}</span>
        {bucket.status === "resolved" && <span className="pill">Resolved</span>}
      </button>
      {open && (
        <div id={`bucket-${bucket.id}`} className="bucket-detail">
          <p>{bucket.summary}</p>
          {bucket.concept_ids.length > 0 && <p className="muted">Concepts: {bucket.concept_ids.join(", ")}</p>}
          <div className="impact">
            <div className="label">Impact</div>
            <p>
              {plural(bucket.report_count, "report")}
              {latest && `, most recent ${timeAgo(latest)}`}
              {locations.length > 0 && ` · ${locations.join(", ")}`}
            </p>
          </div>
          <div className="label">Attendee reports</div>
          {reports.length === 0 ? (
            <p className="muted">No reports loaded for this bucket.</p>
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
