# Friction ontology

`friction.ttl` is the source of truth: a SKOS concept scheme (`fd:` = `https://haikei.dev/ontology/friction#`) of conference-attendee friction, with 11 top concepts (Venue, Accessibility, Schedule, Connectivity, FoodAndBeverage, Registration, Content, SafetyAndConduct, Transport, SponsorsAndExpo, Comfort) and up to three levels. The Elastic index is a compiled projection of it.

```sh
uv run --with rdflib python ontology/compile.py                 # regenerate build/
uv run --with rdflib --with pytest pytest ontology/tests -q     # structural tests
```

Build artifacts (committed, deterministic, sorted by `id`):

- `build/concepts.json` holds one record per concept: `id` (`fd:WifiOutage`), `iri`, `pref_label`, `alt_labels`, `definition`, `broader`, `ancestors` (transitive broader, excluding self), `path` (`Connectivity/Wifi/WifiOutage`), `related`, `top_concept`.
- `build/synonyms.json` holds `{"id", "synonyms"}` rules in Elastic synonyms-set format (lowercase, comma equivalence) for the `friction-desk-concepts` set.

Authoring rules, all enforced by the tests:

- Every concept has `prefLabel`, `definition`, and `broader`. Top concepts are the only exception to `broader`.
- No broader cycles.
- No label (pref or alt) is shared by two concepts, because a shared term would merge their synonym sets.
- After editing the `.ttl`, rerun `compile.py`. The test suite fails if `build/` is stale.

Concepts describe facilities, services and problems, never attributes of people. For example, "prayer room unavailable" is a facility issue and says nothing about anyone's religion.
