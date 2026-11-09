// Mock-mode stand-in for the backend triage agent: a tiny keyword concept
// linker plus token-overlap bucket matching, producing the contract's
// TriageResult (with governance events). Not the real agent.
import type { Bucket, BucketSearchResult, ConceptTag, GovernanceEvent, Report, TriageResult } from "./types";

/** Contract confidence policy: >= this proposes an existing bucket. */
export const HIGH_CONFIDENCE = 0.75;
const REVIEW_FLOOR = 0.35;

interface MockConcept {
  id: string;
  label: string;
  top: string; // top concept id
  keywords: string[];
}

const TOP_LABELS: Record<string, string> = {
  "fd:Venue": "Venue",
  "fd:Accessibility": "Accessibility",
  "fd:Schedule": "Schedule",
  "fd:Connectivity": "Connectivity",
  "fd:FoodAndBeverage": "Food and beverage",
  "fd:Registration": "Registration",
  "fd:Content": "Content",
  "fd:SafetyAndConduct": "Safety and conduct",
  "fd:Transport": "Transport",
  "fd:SponsorsAndExpo": "Sponsors and expo",
  "fd:Comfort": "Comfort",
};

const CONCEPTS: MockConcept[] = [
  { id: "fd:WifiOutage", label: "Wi-Fi outage", top: "fd:Connectivity", keywords: ["wifi", "wi-fi", "network", "internet", "disconnected", "disconnect"] },
  { id: "fd:StepFreeAccess", label: "Step-free access", top: "fd:Accessibility", keywords: ["wheelchair", "ramp", "step-free", "accessible"] },
  { id: "fd:BlockedEntrance", label: "Blocked entrance", top: "fd:Venue", keywords: ["entrance", "blocked", "obstructed"] },
  { id: "fd:ScheduleMismatch", label: "Schedule mismatch", top: "fd:Schedule", keywords: ["schedule", "keynote", "agenda"] },
  { id: "fd:EventApp", label: "Event app", top: "fd:Schedule", keywords: ["app"] },
  { id: "fd:DietaryOptions", label: "Dietary options", top: "fd:FoodAndBeverage", keywords: ["vegetarian", "vegan", "gluten", "halal", "dietary"] },
  { id: "fd:FoodShortage", label: "Food shortage", top: "fd:FoodAndBeverage", keywords: ["lunch", "food", "snacks", "coffee"] },
  { id: "fd:Temperature", label: "Room temperature", top: "fd:Comfort", keywords: ["cold", "hot", "freezing", "temperature"] },
  { id: "fd:BadgeQueue", label: "Badge pickup queue", top: "fd:Registration", keywords: ["badge", "queue", "registration"] },
  { id: "fd:Signage", label: "Signage", top: "fd:Venue", keywords: ["sign", "signs", "signage", "door"] },
];

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

const round = (n: number) => Math.round(n * 100) / 100;

export function topConceptLabel(id: string | undefined): string | null {
  if (!id) return null;
  const c = CONCEPTS.find((x) => x.id === id);
  return TOP_LABELS[c?.top ?? id] ?? null;
}

/** Keyword concept linking (method "exact"), mirroring search.link_concepts. */
export function linkConcepts(text: string): Pick<Report, "concept_tags" | "concept_ids" | "concept_ancestors"> {
  const t = tokens(text);
  const hits = CONCEPTS.filter((c) => c.keywords.some((k) => t.has(k)));
  const concept_tags: ConceptTag[] = hits.map((c) => ({ concept_id: c.id, label: c.label, confidence: 0.9, method: "exact" }));
  return {
    concept_tags,
    concept_ids: hits.map((c) => c.id),
    concept_ancestors: [...new Set(hits.map((c) => c.top))],
  };
}

const allow = (tool: string, rule: string, reason: string): GovernanceEvent => ({ tool, decision: "allow", rule, reason, at: new Date().toISOString() });

export function triage(report: Report, buckets: Bucket[], members: Report[]): TriageResult {
  const rt = tokens(`${report.description} ${report.location ?? ""}`);
  const scored: BucketSearchResult[] = buckets
    .filter((b) => b.status === "open")
    .map((bucket) => {
      const text = [bucket.title, bucket.summary, ...members.filter((m) => m.bucket_id === bucket.id).map((m) => `${m.description} ${m.location ?? ""}`)].join(" ");
      const lexical = overlap(rt, tokens(text));
      const conceptHit = report.concept_ids.some((id) => bucket.concept_ids.includes(id)) ? 1 : 0;
      return { bucket, score: round(0.6 * lexical + 0.4 * conceptHit) };
    })
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  const governance = [
    allow("friction.link_concepts", "allow-read-tools", "Read-only tool; agent role permitted."),
    allow("friction.search_buckets", "allow-read-tools", "Read-only tool; agent role permitted."),
    allow("friction.propose_bucket", "allow-agent-propose", "Agents may propose; organizer confirms."),
  ];
  const base = { concept_ids: report.concept_ids, candidates: scored, governance, extractor_version: "mock-0.1" };
  const best = scored[0];
  const confidence = Math.min(0.97, best?.score ?? 0);
  const labels = report.concept_tags.map((t) => t.label).join(", ") || "no linked concepts";

  if (best && confidence >= HIGH_CONFIDENCE) {
    return {
      ...base,
      disposition: "existing_bucket",
      bucket_id: best.bucket.id,
      proposed_title: null,
      proposed_summary: null,
      confidence,
      rationale: `Same concepts (${labels}) and similar wording to “${best.bucket.title}”.`,
    };
  }
  if (best && confidence >= REVIEW_FLOOR) {
    return {
      ...base,
      disposition: "needs_review",
      bucket_id: null,
      proposed_title: null,
      proposed_summary: null,
      confidence,
      rationale: `Partially matches “${best.bucket.title}” (${labels}), but not confidently enough to propose it.`,
    };
  }
  const words = report.description.split(/\s+/).slice(0, 7).join(" ");
  return {
    ...base,
    disposition: "new_bucket",
    bucket_id: null,
    proposed_title: words.length < report.description.length ? `${words}…` : words,
    proposed_summary: report.location ? `${report.description} (${report.location})` : report.description,
    confidence: round(0.85 - confidence),
    rationale: best
      ? `Closest open issue (“${best.bucket.title}”) shares too little with this report (${labels}).`
      : `No open issue covers these concepts (${labels}).`,
  };
}
