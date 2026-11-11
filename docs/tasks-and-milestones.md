# Tasks and Milestones

This plan separates the **core demo** from **stretch features**. Do not start stretch work until the end-to-end core path is working. The frontend and backend can proceed in parallel after agreeing on the API contract and report/bucket model.

## Milestone 0 — Align and unblock

- [x] Select Python/FastAPI to reuse existing triage code and scaffold the backend API.
- [x] Use the existing hosted Elasticsearch deployment as the canonical store for reports and buckets; app teardown must leave the hosted cluster/data untouched.
- [x] Confirm hosted Elasticsearch, Kei workspace, and configured model providers are available. Keep credentials in Kubernetes Secrets; wire the runtime in the cluster following `kei-chat-harness`.
- [x] Define initial `Report`/`Bucket` schemas and API boundary (`POST/GET /api/reports`, `GET /api/buckets`, `GET /api/buckets/search`). `TriageResult` is defined in #3.
- [x] Create seeded reports and buckets, including same-issue reports phrased differently, unrelated reports, and one ambiguous case. (#8: 12 buckets, 60 reports)
- [x] Keep attendee intake anonymous; the submission schema rejects identity/contact fields.

- [x] Add Helm deployment scaffolding and local Make targets; the release runs in a dedicated namespace and teardown leaves hosted Elasticsearch untouched.
- [ ] Confirm the image registry, hosted Elasticsearch endpoint, and Kubernetes Secret name/key; deploy and verify API connectivity. (Open: #7 UI hosting, then #6 deploy runbook; verify with `scripts/e2e-smoke.sh`.)
- [ ] Add Kei runtime/token Secret wiring following the existing `kei-chat-harness` Kubernetes pattern before model-backed triage. (The ExternalSecret is in #7 and off by default; waiting on T201.)

**Exit:** the API can be deployed from local to the existing cluster, connects to hosted Elasticsearch, and can be removed without affecting the hosted Elasticsearch deployment.

## Milestone 1 — Thin end-to-end vertical slice (core)

- [x] Build attendee report form and submission confirmation.
- [x] Implement initial report submission and persistence in hosted Elasticsearch.
- [x] Build organizer page with a basic report inbox and bucket list. (#4)
- [x] Return a temporary deterministic triage result (seeded rules/mock) so the entire UI flow works before model integration. (#3: concept-overlap fallback, used while no LLM is available)

**Exit:** a report submitted on page one appears on page two with a proposed disposition.

## Milestone 2 — Search and bucket triage (core)

- [x] Add Elasticsearch mappings and index initialization for reports and buckets.
- [x] Index seeded and newly submitted reports/buckets. (#2, `POST /api/admin/reset`)
- [x] Implement hybrid candidate-bucket retrieval. (#2: RRF of lexical with SKOS synonyms + `semantic_text`, boosted by concept-ancestor overlap; see `docs/ontology-skos-to-elastic.md`)
- [x] Add structured agent classification: update an existing bucket or propose a new one, with rationale and confidence. (#3 `TriageResult`; uses the fallback until an LLM is enabled)
- [x] Add confidence/ambiguity handling; avoid silent merges when uncertain. (`needs_review` disposition; nothing is assigned without organizer confirm)
- [x] Show the match/new-bucket explanation in the organizer UI. (#4)

**Exit:** demo both branches: a report updates an existing bucket and a distinct report proposes a new bucket.

## Milestone 3 — Human confirmation and Kei governance (core)

- [x] Add organizer confirm/correct actions and persist the final assignment. (#3, #4)
- [x] Define narrow agent tools and corresponding Kei policies for relevant searches and mutations. (#3: `friction.search_buckets`, `friction.assign_report`; tool manifest exported)
- [ ] Wire the app's agent calls through the available Kei-governed runtime path. (Partly done: calls go through agentware with a local fail-closed evaluator; switching to the Kei runtime waits on T201.)
- [x] Verify allowed actions execute and denied/unavailable authorization prevents governed mutations. (Verified live against Elastic with `scripts/e2e-smoke.sh`)
- [x] Show or explain the authorization/audit result in the demo without exposing secrets or unnecessary attendee data. (Governance panel and `/api/audit`; audit logs argument lengths, not values)
- [x] Add tests for allow, deny, unavailable runtime, and no-mutation-on-deny. (`backend/tests/test_triage.py`)

**Exit:** organizer-approved changes persist, and Kei denial fails closed.

## Milestone 4 — Demo reliability and polish (core)

- [x] Add loading, empty, validation, retry, and error states. (#4)
- [x] Add accessible labels, keyboard flow, focus states, and clear attendee confirmation. (#4; assistive-technology testing is still a follow-up)
- [x] Add a one-command or documented startup path and reliable seeded reset. (#12 `demo/up.sh` with `RESET=1`)
- [x] Run the complete demo flow from a clean start and fix integration failures. (#12 Playwright walkthrough, #10 smoke test)
- [x] Prepare a short narrative: repeated reports → grouped bucket; distinct issue → new bucket; organizer confirms; Kei decision is visible. (`docs/demo-script.md`)

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
