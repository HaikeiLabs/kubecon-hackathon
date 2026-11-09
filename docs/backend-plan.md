# Backend Plan: Conference Friction Desk

## Goal

Provide a reliable path from attendee submission to organizer-reviewed issue bucket. For each report, retrieve relevant existing buckets, propose either an update to a bucket or a new bucket, and return enough evidence for the organizer UI to explain the proposal.

## Proposed flow

1. Validate and persist the attendee report.
2. Search existing open buckets in Elasticsearch using keyword and semantic/vector signals (hybrid search); optionally include conference schedule/venue context where available.
3. Give the top relevant buckets and the new report to the triage agent. Ask it to return a structured proposal: match an existing bucket, or suggest a new one, with a concise rationale and confidence.
4. Apply a deterministic confidence policy:
   - A high-confidence candidate can be presented as a proposed bucket update.
   - A low-confidence or ambiguous result becomes a proposed new bucket or an organizer-review case; do not silently merge unrelated reports.
   - For the hackathon demo, favor organizer confirmation over automatic irreversible changes.
5. Persist the report and proposal, then show it on the organizer page. On organizer confirmation/correction, update the bucket/report relationship and index the resulting bucket state.
6. Record a privacy-conscious audit trail of governed agent decisions and organizer actions.

The agent should not invent conference facts: recommendations must be grounded in the report and retrieved context. Store the attendee's original report separately from generated summaries.

## Core features

- Report submission, validation, persistence, and retrieval.
- Elasticsearch index for reports and issue buckets; mappings support text search and vector search if embeddings are available.
- Hybrid retrieval of candidate buckets, with duplicate/dissimilar seeded examples for the demo.
- Structured agent output for proposed bucket match/new bucket, summary, rationale, and suggested next action.
- Organizer confirmation/correction endpoint and persistent bucket assignment.
- Kei governance for the agent's meaningful data/action tools. Define the tool boundaries and policy with the Kei setup; govern searches over conference data and mutations such as creating/updating buckets. On denial or runtime/policy failure, fail closed for the governed action and expose a safe, understandable UI state.
- Minimal logs that avoid storing unnecessary attendee personal data. Keep credentials and provider secrets out of the app and index.
- Deterministic tests for match/no-match, ambiguous match, denied action, and persistence/indexing behavior.

## Stretch features

- **Draft PR workflow:** for reports classified as a website/schedule defect, retrieve relevant repository context and use the existing bug-triage flow to draft a PR. Never merge or auto-apply in the MVP; display the draft status/link and require human review.
- **Discord intake:** adapt the existing bot to call the same report-submission/triage flow; do not fork the business logic or create a second data store.
- **Conference context enrichment:** index schedule, talk abstracts, maps, access guidance, and relevant venue information; cite the retrieved source in organizer recommendations.
- **Impact analysis:** aggregate report volume and trends by bucket, location, time, and accessibility-related concern. Avoid inferring sensitive characteristics about individual attendees.
- **Dash0/OpenTelemetry:** trace submission, retrieval, model, Kei authorization, and organizer action steps; show latency/failure signals during the demo.
- **Live update delivery:** notify the organizer UI when a report or bucket changes.

## Data and API boundaries

Use the hosted Elasticsearch deployment as the canonical store for reports and buckets for the hackathon, avoiding a second database. The application runs in Kubernetes and connects to the hosted cluster over HTTPS using an API key read from a Kubernetes Secret. The Elasticsearch deployment and its stored data are external to this repo's Kubernetes release; deleting the app release must not delete the hosted cluster or its data.

Agree on the frontend contract before parallel implementation. Minimum operations are:

- Submit a report.
- List reports/buckets for the organizer view.
- Get report/bucket detail.
- Confirm or correct a proposed bucket assignment.

The initial implementation uses Python/FastAPI. The first API surface is `POST /api/reports`, `GET /api/reports`, `GET /api/buckets`, and `GET /api/buckets/search`. Validate all inputs server-side and keep model-generated fields explicitly marked as proposals.

## Kei integration boundary

Kei governs the agent's tool calls and records authorization decisions; it is not the report database, vector store, or LLM. Keep tool definitions narrow and explicit (for example, search relevant buckets, create a proposed bucket, attach a report to a confirmed bucket). The user/organizer identity and allowed action must be represented correctly. Test both allowed and denied paths; if Kei authorization is unavailable, do not execute governed mutations. The runtime will be deployed in Kubernetes following the existing `kei-chat-harness` pattern. Confirm its agent, policies, token Secret source, and model-profile configuration before wiring model calls; do not put credentials in Helm values or the repository.

## Acceptance criteria

- A submitted report is persisted and appears in organizer results.
- Related reports can match an existing bucket based on retrieval plus triage; unrelated reports produce a new-bucket proposal.
- Match rationale and confidence are returned to the UI; uncertain cases remain reviewable.
- Organizer confirmation/correction persists and subsequent search reflects the updated bucket.
- Kei allow/deny behavior is exercised for governed operations; denied actions do not mutate data.
- Tests cover duplicate, no-match, ambiguous, failure, and authorization-denied cases.
