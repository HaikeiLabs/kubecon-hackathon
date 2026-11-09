# Friction Desk demo seed data

Hand-written demo data for `reset_and_seed()` (backend/app/search.py). The app
never depends on anything but these two files.

- `buckets.json` — 12 organizer buckets with stable ids (`bucket-...`). Each
  carries `concept_ids` that must exist in `ontology/build/concepts.json`;
  `concept_ancestors`, `category` and `updated_at` are derived by the loader.
- `reports.json` — 60 attendee reports with stable ids (`rpt-...`).
  Concept tags are intentionally left empty so the live `link_concepts()`
  pass tags them at reset time.

## Demo shape

- **12 pre-assigned reports** (one-or-two per bucket, status `confirmed`,
  `bucket_id` set) so every bucket shows a populated inbox cluster; each
  bucket's `report_count` matches those assignments exactly.
- **47 unassigned reports** so the organizer triage flow has live work:
  near-duplicate paraphrases of each bucket topic in different wording
  (e.g. seven distinct "Wi-Fi hall B is unusable" variants that should all
  cluster into `bucket-wifi-slow`), plus valid friction that matches **no**
  seeded bucket (shuttle timetable, recordings stuck processing, swag queue,
  elevator out of service...) which triage should propose as *new buckets*,
  plus four clearly-off-topic posts (cafe recommendation, spare ticket,
  board-game meetup, running routes) and four zero-friction praise posts that
  should match nothing and stay untriaged.
- Report texts are deliberately **not** copied from `backend/eval/gold.jsonl`
  (the held-out eval set); backend/tests/test_seed.py asserts the disjoint.

## Later: generating more reports with SmallMinds WellDB / MongTap

MongTap (https://github.com/smallmindsco/MongTap) is the open-source on-ramp to
SmallMinds' WellDB (https://www.smallminds.co/welldb), a "generative database"
where tables are DataFlood statistical models. It is a MongoDB-compatible MCP
server: you "train" a collection by inserting sample documents, and queries
generate new documents from the learned statistical model — no storage, and
two generation knobs in queries (`$seed` for deterministic repeats, `$entropy`
0–1 for randomness). None of this is wired into the app; this section is a
future-use note only.

**What we would train DataFlood models on.** Split the hand-written corpus by
cluster so each model shares one statistical "shape":

- one model per demo bucket's unassigned reports (`concerns-wifi`,
  `concerns-av`, `concerns-wayfinding`, ...), trained on the report documents
  they actually belong to;
- one `new-issue-friction` model from the 7 bucketless friction reports;
- one `off-topic` and one `praise` model from the 8 no-concept posts;
- one `scenario` model trained on the 12 buckets (or a description string)
  to generate plausible *new* bucket tuples.

Each sample document carries the seed-record fields the pipeline cares about:
`description`, `location`, and either the expected `bucket_id`/`status` or a
`label` field (friction/off-topic/praise). A post-generation step would strip
that label field before writing into `reports.json`, and never invent the
`concept_tags` (those must stay empty so the live linker tags them).

**Seed and entropy choices.**

- *Reproducible demo:* `generateDataModel` per bucket model once, then
  `queryModel({model:"concerns-wifi", count:..., query:{$seed:20261109,
  $entropy:0.25}})` — fixed seed and low entropy keep every run of the KubeCon
  demo byte-identical (same paraphrase families, same near-duplicates) while
  still varying wording enough that sorters see "different" texts.
- *Distribution tuning:* pass an explicit seed-map per model (e.g. concerns-wifi
  `$seed:11`, praise `$seed:99`) and bake the chosen numbers into the script
  that emits `reports.json`, so the mix of ~70% friction / 15% new-bucket /
  15% no-friction is stable.
- *Larger triage-training corpus:* same models with `$seed:20261110` and
  `$entropy:0.6` for several thousand low-similarity reports — good for
  load-testing the API and measuring linker precision/recall drift, the kind
  of volume DataFlood advertises (thousands of generated docs/second).

MongTap compatibility caveats if we ever do this: run its MCP server only as a
local authoring tool (env `MONGTAP_STORAGE`, schema via `models://{name}/schema`),
generate via a Mongo client against the started server, and hand-reject any
generated report whose `description` is shorter than 8 chars or duplicates a
held-out `backend/eval/gold.jsonl` row. Nothing in `backend/`
imports or calls it; the app keeps reading plain `seed/*.json`.

## Verification

`backend/tests/test_seed.py` validates the JSON statically (parsing, concept
ids against the real ontology build, bucket-reference closure, and
report_count consistency) without touching any Elastic index.
