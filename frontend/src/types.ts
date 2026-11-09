// Mirrors backend/app/models.py. TriageResult is not in the backend yet;
// it is the frontend's proposed contract until agent triage lands.

export type ReportStatus = "untriaged" | "proposed" | "confirmed";

export interface ReportSubmission {
  description: string;
  location?: string | null;
}

export interface Report {
  id: string;
  description: string;
  location: string | null;
  created_at: string;
  status: ReportStatus;
  bucket_id: string | null;
}

export interface Bucket {
  id: string;
  title: string;
  summary: string;
  status: "open" | "resolved";
  report_count: number;
  updated_at: string;
}

export interface BucketSearchResult {
  bucket: Bucket;
  score: number;
}

/** AI-generated proposal for a report. Every field here is a suggestion, not a fact. */
export type TriageResult =
  | {
      kind: "existing";
      report_id: string;
      bucket_id: string;
      confidence: number; // 0..1
      explanation: string;
      suggested_action: string;
    }
  | {
      kind: "new";
      report_id: string;
      proposed_title: string;
      proposed_summary: string;
      confidence: number;
      explanation: string;
      suggested_action: string;
    };

/** Organizer decision on a report. */
export type Assignment =
  | { kind: "existing"; bucket_id: string }
  | { kind: "new"; title: string; summary: string };
