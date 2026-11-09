// Temporary deterministic triage (Milestone 1) so the UI flow works before
// model-backed triage exists. Simple token overlap — not the real agent.
import type { Bucket, Report, TriageResult } from "./types";

const STOP = new Set(
  "a an the and or of to in on at for is it its this that was were be been are with from by as i my me we our there their they not no but so very just near room during session times three keeps had get got".split(" "),
);

function tokens(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, " ")
      .split(/\s+/)
      .filter((t) => t.length > 1 && !STOP.has(t)),
  );
}

function overlap(a: Set<string>, b: Set<string>): number {
  if (!a.size || !b.size) return 0;
  let hit = 0;
  for (const t of a) if (b.has(t)) hit++;
  return hit / Math.min(a.size, b.size);
}

export const HIGH_CONFIDENCE = 0.6;

export function triage(report: Report, buckets: Bucket[], members: Report[]): TriageResult {
  const rt = tokens(`${report.description} ${report.location ?? ""}`);
  let best: { bucket: Bucket; score: number; shared: string[] } | null = null;
  for (const bucket of buckets.filter((b) => b.status === "open")) {
    const text = [bucket.title, bucket.summary, ...members.filter((m) => m.bucket_id === bucket.id).map((m) => `${m.description} ${m.location ?? ""}`)].join(" ");
    const bt = tokens(text);
    const score = overlap(rt, bt);
    if (!best || score > best.score) best = { bucket, score, shared: [...rt].filter((t) => bt.has(t)) };
  }

  const confidence = Math.min(0.97, Math.round((best?.score ?? 0) * 100) / 100);
  if (best && best.score >= 0.3) {
    return {
      kind: "existing",
      report_id: report.id,
      bucket_id: best.bucket.id,
      confidence,
      explanation: `Shares key terms with this issue: ${best.shared.slice(0, 5).join(", ")}.`,
      suggested_action:
        confidence >= HIGH_CONFIDENCE
          ? "Attach to this issue and bump its priority."
          : "Weak match — check whether this is really the same problem.",
    };
  }
  const words = report.description.split(/\s+/).slice(0, 7).join(" ");
  return {
    kind: "new",
    report_id: report.id,
    proposed_title: words.length < report.description.length ? `${words}…` : words,
    proposed_summary: report.location ? `${report.description} (${report.location})` : report.description,
    confidence: Math.round((1 - (best?.score ?? 0)) * 70) / 100,
    explanation: best
      ? `Closest open issue ("${best.bucket.title}") shares too little with this report.`
      : "There are no open issues to compare against.",
    suggested_action: "Create a new issue and assign an owner.",
  };
}
