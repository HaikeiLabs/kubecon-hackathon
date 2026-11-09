# From SKOS to Elasticsearch

The friction ontology is written in SKOS (`ontology/friction.ttl`). Elasticsearch
doesn't read RDF, and the app doesn't run a reasoner. Instead,
`ontology/compile.py` turns the inferences a reasoner would make into plain data
at build time, and Elastic uses that data through ordinary index features:
keyword fields, a synonym set and `semantic_text`.

```
friction.ttl ──compile.py──▶ build/concepts.json ──▶ friction-desk-concepts-v1 (concept docs)
   (SKOS)                    build/synonyms.json ──▶ synonym set "friction-desk-concepts"
                                                     └─▶ fd_synonyms filter, search time, all v2 indices
```

Edit only `friction.ttl`. Then run `uv run --with rdflib python ontology/compile.py`.
The ontology tests fail if `build/` is out of date. `POST /api/admin/reset`
reloads the concept documents and the synonym set into Elastic.

## Mapping

| SKOS (`friction.ttl`) | Compiled field (`build/`) | How Elastic uses it |
|---|---|---|
| concept IRI `fd:WifiOutage` | `id` (CURIE), `iri` | `keyword`. Reports and buckets reference concepts by `id`. |
| `skos:prefLabel` | `pref_label` | `text` and `.keyword`, boosted ×3 in lexical concept search. Copied into the `semantic` field. Shown in the UI as the concept chip. Also the first term of the concept's synonym rule. |
| `skos:altLabel` | `alt_labels` | `text`, boosted ×2 in lexical concept search. Matched as exact phrases when tagging reports. Every alt label becomes a term in the concept's synonym rule. **Not** copied into `semantic`. |
| `skos:definition` | `definition` | `text`, used in lexical concept search. Copied into the `semantic` field, so it drives semantic concept matching. |
| `skos:broader` | `broader` | `keyword`, the direct parents. |
| `skos:broader`, transitive | `ancestors` | Computed by the compiler (this replaces a reasoner). Stored on each report and bucket as `concept_ancestors`. |
| `skos:broader`, first sorted chain | `path` (`Connectivity/Wifi/WifiOutage`), `top_concept` | `keyword`, for display and grouping. |
| `skos:related` | `related` | `keyword`. Stored, but nothing ranks on it yet. |
| `prefLabel` + `altLabel`s | `synonyms.json`: `{"id", "synonyms": "a, b, c"}` | One comma-equivalence rule per concept in the Elastic synonym set `friction-desk-concepts`. |

## What each piece does at runtime

### Synonyms: labels count as the same term in search

`build_synonyms` lowercases every label, replaces commas, and joins the
`prefLabel` and `altLabel`s into one rule:

```json
{"id": "fd:NoVegetarianOption",
 "synonyms": "no vegetarian option, no vegetarian, no veggie, only meat, vegetarian ran out, …"}
```

The `fd_synonyms` filter (`synonym_graph`, `updateable: true`) runs only in the
**search** analyzer (`fd_text`), never at index time. So a query for "only meat"
also matches text that says "no veggie", and the synonym set can be updated
without reindexing.

**Implication:** an `altLabel` that is fine in SKOS becomes full equivalence in
Elastic. A bare topic word such as "vegetarian" would make "vegetarian"
mean the same as "only meat". An alt label should name the *problem* ("no vegetarian
options"), not the topic. The ontology tests also reject a label shared by two
concepts, because a shared term would merge their rules.

### Concept linking: tagging a report

`link_concepts(text)` runs two passes:

1. **Exact** (`method: "exact"`): a word-boundary phrase match of the `prefLabel`
   and `altLabel`s against the folded report text.
2. **Hybrid** (`method: "hybrid"`): an RRF query over the concepts index that
   combines lexical `multi_match` (`pref_label^3`, `alt_labels^2`, `definition`)
   with semantic search on `semantic`, which embeds `prefLabel` and `definition`.
   It keeps only strong hits (`HYBRID_MIN_SCORE`, `HYBRID_RELATIVE_CUTOFF`,
   `HYBRID_MAX_TAGS`).

Both passes keep the most specific concept. A matched ancestor of another
matched concept is dropped from the tags, because the closure keeps it anyway.

Because the semantic side matches on meaning, it can tag text that no label
covers, including praise ("the veggie options were great" →
`NoVegetarianOption`). Removing alt labels doesn't prevent that. It needs a
change in search, such as ignoring positive sentences.

### Ancestor closure: broader without a reasoner

When a report is tagged, `concept_closure` adds every compiled `ancestor`.
Those go into `concept_ancestors` (`keyword`) on the report and its bucket:

```
concept_ids:       [fd:NoVegetarianOption]
concept_ancestors: [fd:DietaryOptions, fd:FoodAndBeverage, fd:NoVegetarianOption]
```

A filter or `terms` query on `fd:FoodAndBeverage` therefore finds every
food-related report without any query-time expansion. Bucket search
(`build_bucket_search_body`) adds a `terms` boost (×2) on `concept_ancestors`
overlap, so a report and a bucket that share a broader concept rank closer even
when their wording differs.

## Authoring checklist

- Add complaint phrasing as an `altLabel` ("wifi keeps cutting out"), not topic
  words ("wifi", "vegetarian").
- Don't use the same label on two concepts. The tests enforce this.
- Write a `definition` that describes the problem in plain words. It is what the
  semantic matcher sees, not the alt labels.
- Put a concept under the most specific `broader`. Add a second `broader` only
  when both parents are true. Search drops a matched ancestor in favor of its
  descendant.
- Measure every change: run `cd backend && uv run --extra dev python -m eval.run_eval`
  (offline), then `--live` against Elastic after a reset. Don't take wording from
  `backend/eval/gold.jsonl`.
