# Demo script

A 2–3 minute walkthrough of Friction Desk. The recorded version is
`demo/record.sh`. It drives the UI with `demo/walkthrough.mjs`, whose caption
for each beat comes from `demo/narration.json`, and can be narrated with a Moshi
voice (`demo/narrate.py`). Keep this file, the captions and the narration in
sync: `demo/narration.json` is the single source for what's said on screen.

## The story in one sentence

At a conference, the same problem gets reported a dozen different ways; Friction
Desk turns that noise into a few actionable buckets, using an ontology to
understand the wording and a governed agent that can only change things when an
organizer says so.

## Setup

```sh
RESET=1 demo/up.sh          # API + UI under launchd, reseed the v2 indices
open http://127.0.0.1:5173/#/report
```

## Beats

| # | On screen | Say |
|---|---|---|
| 1 | Attendee report form | "An attendee hits a problem. No login, no account: they just say what happened and where." |
| 2 | Submit the Hall C Wi-Fi report | "When they submit, the API links the text to concepts in our friction ontology and asks the triage agent where it belongs." |
| 3 | Organizer inbox, new card highlighted | "On the organizer side, the report lands in the inbox, waiting for review." |
| 4 | Concept chip "Slow Wi-Fi" | "'Wi-Fi keeps dropping' became the Slow Wi-Fi concept. The ontology is SKOS; its labels compile into Elastic synonyms, and hybrid search does the rest." |
| 5 | AI suggestion box | "Triage proposes the existing bucket for Wi-Fi drops, with its confidence and the reason. Nothing has changed yet. It's only a suggestion." |
| 6 | Governance panel | "Every tool the agent can call goes through a fail-closed policy, and every decision is audited." |
| 7 | Switch to "Attendee agent", click Confirm | "So what if the attendee's own agent tries to make that change?" |
| 8 | Red "Denied by policy" next to the audit deny | "Denied by policy, and nothing was written. The deny shows up in the audit log." |
| 9 | Switch to "Organizer", click Confirm | "The organizer confirms instead." |
| 10 | Card leaves inbox, audit allow on top | "Now the report is filed into the bucket, and the allow is audited too." |
| 11 | Closing caption | "Friction Desk: ontology search on Elastic, and an agent that can only act when a person says so." |

## Live extension: the new-bucket branch (optional, ~30 s)

The recording shows a report that joins an existing bucket. To show the other
branch live, submit a report no bucket covers:

> "Someone parked a scooter blocking the step-free entrance to Hall D."

Triage proposes a **new bucket** ("no candidate bucket shares concepts"), and
the confirm creates it. Say: "Something nobody has reported before doesn't get
forced into the nearest bucket. It's proposed as a new one."

## Honest answers for Q&A

- **Is the triage an LLM?** Not in this demo. The model endpoints on our Elastic
  project aren't enabled, so triage uses its deterministic fallback: overlap in
  ontology concepts plus hybrid bucket search. The rationale says "Fallback"
  and the extractor version shows it. With a model enabled, the same governed
  tools and UI are used.
- **Is that Kei?** Policy and audit use the agentware SDK with a local evaluator
  that denies by default. The Kei runtime is next (T201); the tool manifest
  is already exported.
- **How good is the concept linking?** On 40 hand-labeled held-out reports,
  live linking scores precision 0.955 and recall 1.0
  (`backend/eval/run_eval.py --live`).
- **Privacy?** Attendee intake is anonymous (the schema rejects identity
  fields), and the audit log records argument lengths, not values.
- **Known gap:** semantic matching can still tag praise ("the veggie options
  were great") as a complaint. That needs a sentiment-aware step in search, not more
  synonyms.

## Reset between runs

Each recorded run adds one report and confirms it. `RESET=1 demo/up.sh`, or
**Reset demo data** in the organizer UI, restores the seed state.
