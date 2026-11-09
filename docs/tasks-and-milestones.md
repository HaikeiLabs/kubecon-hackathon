# Tasks and Milestones

This plan separates the **core demo** from **stretch features**. Do not start stretch work until the end-to-end core path is working. The frontend and backend can proceed in parallel after agreeing on the API contract and report/bucket model.

## Milestone 0 — Align and unblock

- [x] Select Python/FastAPI to reuse existing triage code and scaffold the backend API.
- [x] Use the existing hosted Elasticsearch deployment as the canonical store for reports and buckets; app teardown must leave the hosted cluster/data untouched.
- [x] Confirm hosted Elasticsearch, Kei workspace, and configured model providers are available. Keep credentials in Kubernetes Secrets; wire the runtime in the cluster following `kei-chat-harness`.
- [x] Define initial `Report`/`Bucket` schemas and API boundary (`POST/GET /api/reports`, `GET /api/buckets`, `GET /api/buckets/search`). TriageResult remains to be defined with the agent integration.
- [ ] Create seeded reports and buckets, including same-issue reports phrased differently, unrelated reports, and one ambiguous case.
- [x] Keep attendee intake anonymous; the submission schema rejects identity/contact fields.

- [x] Add Helm deployment scaffolding and local Make targets; the release runs in a dedicated namespace and teardown leaves hosted Elasticsearch untouched.
- [ ] Confirm the image registry, hosted Elasticsearch endpoint, and Kubernetes Secret name/key; deploy and verify API connectivity.
- [ ] Add Kei runtime/token Secret wiring following the existing `kei-chat-harness` Kubernetes pattern before model-backed triage.

**Exit:** the API can be deployed from local to the existing cluster, connects to hosted Elasticsearch, and can be removed without affecting the hosted Elasticsearch deployment.

## Milestone 1 — Thin end-to-end vertical slice (core)

- [ ] Build attendee report form and submission confirmation.
- [x] Implement initial report submission and persistence in hosted Elasticsearch.
- [ ] Build organizer page with a basic report inbox and bucket list.
- [ ] Return a temporary deterministic triage result (seeded rules/mock) so the entire UI flow works before model integration.

**Exit:** a report submitted on page one appears on page two with a proposed disposition.

## Milestone 2 — Search and bucket triage (core)

- [x] Add Elasticsearch mappings and index initialization for reports and buckets.
- [ ] Index seeded and newly submitted reports/buckets.
- [ ] Implement hybrid candidate-bucket retrieval (initial lexical candidate search is scaffolded; embeddings/vector search remains).
- [ ] Add structured agent classification: update an existing bucket or propose a new one, with rationale and confidence.
- [ ] Add confidence/ambiguity handling; avoid silent merges when uncertain.
- [ ] Show the match/new-bucket explanation in the organizer UI.

**Exit:** demo both branches: a report updates an existing bucket and a distinct report proposes a new bucket.

## Milestone 3 — Human confirmation and Kei governance (core)

- [ ] Add organizer confirm/correct actions and persist the final assignment.
- [ ] Define narrow agent tools and corresponding Kei policies for relevant searches and mutations.
- [ ] Wire the app's agent calls through the available Kei-governed runtime path.
- [ ] Verify allowed actions execute and denied/unavailable authorization prevents governed mutations.
- [ ] Show or explain the authorization/audit result in the demo without exposing secrets or unnecessary attendee data.
- [ ] Add tests for allow, deny, unavailable runtime, and no-mutation-on-deny.

**Exit:** organizer-approved changes persist, and Kei denial fails closed.

## Milestone 4 — Demo reliability and polish (core)

- [ ] Add loading, empty, validation, retry, and error states.
- [ ] Add accessible labels, keyboard flow, focus states, and clear attendee confirmation.
- [ ] Add a one-command or documented startup path and reliable seeded reset.
- [ ] Run the complete demo flow from a clean start and fix integration failures.
- [ ] Prepare a short narrative: repeated reports → grouped bucket; distinct issue → new bucket; organizer confirms; Kei decision is visible.

**Exit:** the core demo can be repeated reliably without manual database editing.

## Stretch backlog (only after core exit)

- [ ] **Draft PR:** connect website/schedule defect reports to the existing bug-triage workflow; create a draft only, never auto-merge.
- [ ] **Discord intake:** route bot reports through the same backend pipeline and display them in the organizer UI.
- [ ] **Conference knowledge retrieval:** add schedule, abstracts, maps, and accessibility guidance as grounded context.
- [ ] **Impact analytics:** show bucket trends, report counts, and affected locations without profiling individuals.
- [ ] **Dash0/OpenTelemetry:** trace the complete report-to-triage flow and demonstrate latency/failure diagnosis.
- [ ] **Live updates:** push new reports and bucket changes to the organizer UI.
- [ ] **Radar:** only if deployment is already on Kubernetes and there is time for a meaningful infrastructure demo.

## Suggested order of ownership

- **Frontend:** page layout, report form, organizer inbox/detail, state handling, accessibility, demo polish.
- **Backend:** schemas/API, persistence and Elasticsearch indexing, retrieval/triage, Kei tool authorization, tests and seed/reset.
- **Pair early:** API contract, bucket match semantics, confirmation behavior, Kei identity/policy setup, and the end-to-end demo narrative.
