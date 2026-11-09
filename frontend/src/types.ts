// Mirrors backend/app/models.py per the friction-desk ontology contract v1
// (wiki: "friction-desk ontology: API and artifact contract v1").

export type ReportStatus = "untriaged" | "proposed" | "confirmed";

export interface ReportSubmission {
  description: string;
  location?: string | null;
}

/** An ontology concept linked to a report. Concept ids are CURIEs, e.g. "fd:WifiOutage". */
export interface ConceptTag {
  concept_id: string;
  label: string;
  confidence: number; // 0..1
  method: "exact" | "hybrid" | "llm";
}

export interface Report {
  id: string;
  description: string;
  location: string | null;
  created_at: string;
  status: ReportStatus;
  bucket_id: string | null;
  concept_tags: ConceptTag[];
  concept_ids: string[];
  concept_ancestors: string[];
  triage: TriageResult | null;
}

export interface Bucket {
  id: string;
  title: string;
  summary: string;
  status: "open" | "resolved";
  report_count: number;
  updated_at: string;
  concept_ids: string[];
  concept_ancestors: string[];
  /** Top concept pref_label, e.g. "Connectivity". */
  category: string | null;
}

export interface BucketSearchResult {
  bucket: Bucket;
  score: number;
}

/** One policy decision on an agent tool call. */
export interface GovernanceEvent {
  tool: string;
  decision: "allow" | "deny";
  rule: string;
  reason: string;
  at: string;
}

export type Disposition = "existing_bucket" | "new_bucket" | "needs_review";

/** AI-generated proposal for a report. Every field here is a suggestion, not a fact. */
export interface TriageResult {
  disposition: Disposition;
  bucket_id: string | null;
  proposed_title: string | null;
  proposed_summary: string | null;
  confidence: number; // 0..1
  rationale: string;
  concept_ids: string[];
  candidates: BucketSearchResult[];
  governance: GovernanceEvent[];
  extractor_version: string;
}

/** Body of POST /api/reports/{id}/confirm — exactly one of bucket_id / new_bucket_title. */
export type ConfirmRequest =
  | { bucket_id: string; new_bucket_title?: undefined; new_bucket_summary?: undefined }
  | { bucket_id?: undefined; new_bucket_title: string; new_bucket_summary?: string };

/** Sent as the X-Role header. Only "organizer" may confirm assignments. */
export type Role = "organizer" | "attendee-agent";
