import json
from pathlib import Path

import pytest

from app import search
from app.models import Report

FIXTURE = Path(__file__).parent / "fixtures" / "concepts.sample.json"


@pytest.fixture
def concepts() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize(
    "text",
    [
        "Hall B wifi down since 9am",
        "Wi-Fi down again near the keynote stage",
        "There is no internet anywhere in the expo hall",
        "WIFI NOT WORKING!!",
    ],
)
def test_exact_linker_maps_variants_to_same_concept(text: str, concepts: list[dict]) -> None:
    tags = search.exact_concept_matches(text, concepts)

    assert [t.concept_id for t in tags] == ["fd:WifiOutage"]
    assert tags[0].method == "exact"
    assert tags[0].confidence == pytest.approx(0.95)


def test_exact_linker_respects_word_boundaries(concepts: list[dict]) -> None:
    assert search.exact_concept_matches("The rampage of questions was fun", concepts) == []


def test_exact_linker_keeps_independent_concepts(concepts: list[dict]) -> None:
    tags = search.exact_concept_matches("Ramp blocked and also no internet", concepts)

    assert {t.concept_id for t in tags} == {"fd:BlockedStepFreeAccess", "fd:WifiOutage"}


def test_closure_adds_ancestors(concepts: list[dict]) -> None:
    closure = search.concept_closure(["fd:WifiOutage"], concepts)

    assert closure == ["fd:Connectivity", "fd:Wifi", "fd:WifiOutage"]
    assert search.concept_category(["fd:WifiOutage"], concepts) == "Connectivity"


def test_apply_concept_tags_fills_ancestors(concepts: list[dict]) -> None:
    report = Report(id="r1", description="wifi down", created_at="2026-11-09T12:00:00Z")
    tags = search.exact_concept_matches(report.description, concepts)

    tagged = search.apply_concept_tags(report, tags, concepts)

    assert tagged.concept_ids == ["fd:WifiOutage"]
    assert tagged.concept_ancestors == ["fd:Connectivity", "fd:Wifi", "fd:WifiOutage"]


def test_link_concepts_without_client_uses_exact_only(concepts: list[dict]) -> None:
    tags = search.link_concepts(None, "no internet", concepts=concepts)

    assert [t.concept_id for t in tags] == ["fd:WifiOutage"]


class StubSearchClient:
    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    def search(self, *, index: str, **body) -> dict:
        self.calls.append({"index": index, **body})
        return {"hits": {"hits": self.hits}}


def _hit(concept_id: str, score: float) -> dict:
    return {"_score": score, "_source": {"id": concept_id, "pref_label": concept_id[3:]}}


def test_hybrid_selection_keeps_only_near_best_above_floor() -> None:
    # Live shape of 'wi-fi ... totally dead' with rank_constant=1 RRF.
    hits = [
        _hit("fd:Wifi", 0.833),
        _hit("fd:WifiOutage", 0.75),
        _hit("fd:SlowWifi", 0.533),
        _hit("fd:WifiLoginProblem", 0.45),
    ]

    assert [t.concept_id for t in search.select_hybrid_concepts(hits)] == ["fd:Wifi"]
    # Relative cut is taken against the best hit not already covered by exact matches.
    kept = search.select_hybrid_concepts(hits, exclude=["fd:Wifi", "fd:Connectivity"])
    assert [(t.concept_id, t.method) for t in kept] == [("fd:WifiOutage", "hybrid")]


def test_hybrid_selection_absolute_floor_and_max_three() -> None:
    assert search.select_hybrid_concepts([_hit("fd:Wifi", 0.6)]) == []
    ties = [_hit(f"fd:C{i}", 0.75) for i in range(5)]
    assert len(search.select_hybrid_concepts(ties)) == 3


def test_prune_ancestor_tags_keeps_most_specific(concepts: list[dict]) -> None:
    tags = [
        search.ConceptTag(concept_id=cid, label=cid, confidence=0.9, method=method)
        for cid, method in [
            ("fd:Wifi", "exact"),
            ("fd:WifiOutage", "hybrid"),
            ("fd:Connectivity", "hybrid"),
            ("fd:StepFreeAccess", "exact"),
        ]
    ]

    kept = search.prune_ancestor_tags(tags, concepts)

    assert [t.concept_id for t in kept] == ["fd:WifiOutage", "fd:StepFreeAccess"]


def test_link_concepts_prefers_exact_and_drops_parent_of_hybrid(concepts: list[dict]) -> None:
    client = StubSearchClient(
        [
            _hit("fd:Wifi", 0.833),
            _hit("fd:WifiOutage", 0.75),
            _hit("fd:StepFreeAccess", 0.533),
        ]
    )

    tags = search.link_concepts(client, "the wi-fi in hall A is totally dead", concepts=concepts)

    # Exact fd:Wifi is superseded by its hybrid child; the weak sibling is cut.
    assert [(t.concept_id, t.method) for t in tags] == [("fd:WifiOutage", "hybrid")]
    assert client.calls[0]["index"] == search.CONCEPTS_INDEX
    assert client.calls[0]["retriever"]["rrf"]["rank_constant"] == 1


def test_link_concepts_exact_wins_over_same_hybrid_hit(concepts: list[dict]) -> None:
    client = StubSearchClient([_hit("fd:WifiOutage", 1.0), _hit("fd:StepFreeAccess", 0.5)])

    tags = search.link_concepts(client, "no internet here", concepts=concepts)

    assert [(t.concept_id, t.method) for t in tags] == [("fd:WifiOutage", "exact")]


def test_synonym_rules_from_labels(concepts: list[dict]) -> None:
    rules = {r["id"]: r["synonyms"] for r in search.synonym_rules(concepts)}

    assert rules["fd_WifiOutage"].startswith("wi-fi outage, wifi down")
    assert "no internet" in rules["fd_WifiOutage"]


def test_mapping_builder_defines_analyzers_and_semantic_fields() -> None:
    defs = search.index_definitions()

    assert set(defs) == {search.CONCEPTS_INDEX, search.REPORTS_INDEX, search.BUCKETS_INDEX}
    assert "friction-desk-reports-v2" in defs and "friction-desk-buckets-v2" in defs
    for body in defs.values():
        analysis = body["settings"]["analysis"]
        synonyms = analysis["filter"]["fd_synonyms"]
        assert synonyms == {
            "type": "synonym_graph",
            "synonyms_set": "friction-desk-concepts",
            "updateable": True,
        }
        assert "fd_synonyms" in analysis["analyzer"]["fd_text"]["filter"]
        assert "fd_synonyms" not in analysis["analyzer"]["fd_text_index"]["filter"]
        assert "number_of_shards" not in json.dumps(body)
        assert body["mappings"]["properties"]["semantic"] == {"type": "semantic_text"}

    buckets = defs[search.BUCKETS_INDEX]["mappings"]["properties"]
    assert buckets["concept_ancestors"] == {"type": "keyword"}
    assert buckets["summary"]["search_analyzer"] == "fd_text"
    assert buckets["summary"]["copy_to"] == ["semantic"]
    reports = defs[search.REPORTS_INDEX]["mappings"]["properties"]
    assert reports["description"]["copy_to"] == ["semantic"]
    assert reports["concept_ids"] == {"type": "keyword"}


def test_bucket_search_body_is_rrf_of_lexical_and_semantic() -> None:
    body = search.build_bucket_search_body("wifi down", ["fd:Connectivity", "fd:Wifi"], k=3)

    assert body["size"] == 3
    lexical, semantic = body["retriever"]["rrf"]["retrievers"]
    lex_bool = lexical["standard"]["query"]["bool"]
    assert lex_bool["filter"] == [{"term": {"status": "open"}}]
    assert lex_bool["should"][0]["multi_match"]["fields"] == ["title^2", "summary"]
    assert lex_bool["should"][1]["terms"]["concept_ancestors"] == ["fd:Connectivity", "fd:Wifi"]
    sem_bool = semantic["standard"]["query"]["bool"]
    assert sem_bool["must"] == [{"semantic": {"field": "semantic", "query": "wifi down"}}]
    assert sem_bool["filter"] == [{"term": {"status": "open"}}]


def test_bucket_search_body_without_concepts_has_no_terms_clause() -> None:
    body = search.build_bucket_search_body("anything", [], k=5)
    should = body["retriever"]["rrf"]["retrievers"][0]["standard"]["query"]["bool"]["should"]

    assert len(should) == 1


def test_search_candidate_buckets_expands_concepts(concepts: list[dict]) -> None:
    client = StubSearchClient(
        [
            {
                "_score": 0.03,
                "_source": {
                    "id": "b1",
                    "title": "Wi-Fi outage",
                    "summary": "Hall B wifi is down",
                    "updated_at": "2026-11-09T12:00:00Z",
                },
            }
        ]
    )

    results = search.search_candidate_buckets(
        client, "no internet", ["fd:WifiOutage"], k=2, concepts=concepts
    )

    assert results[0].bucket.id == "b1"
    terms = client.calls[0]["retriever"]["rrf"]["retrievers"][0]["standard"]["query"]["bool"][
        "should"
    ][1]["terms"]["concept_ancestors"]
    assert terms == ["fd:Connectivity", "fd:Wifi", "fd:WifiOutage"]


def test_missing_concepts_file_yields_no_concepts(tmp_path: Path) -> None:
    assert search.read_concepts(tmp_path / "missing.json") == []


@pytest.mark.skipif(not search.DEFAULT_CONCEPTS_PATH.is_file(), reason="ontology build not present")
def test_real_ontology_links_wifi_variants_and_closes_ancestors(monkeypatch) -> None:
    monkeypatch.delenv("FD_CONCEPTS_PATH", raising=False)
    concepts = search.read_concepts()
    assert search.default_concepts_path() == search.DEFAULT_CONCEPTS_PATH
    assert {"id", "pref_label", "alt_labels", "ancestors", "top_concept"} <= set(concepts[0])

    for text in ["wifi down in hall B", "wi-fi down again", "no internet in room 3"]:
        assert [t.concept_id for t in search.link_concepts(None, text)] == ["fd:WifiOutage"]
    assert search.concept_closure(["fd:WifiOutage"], concepts) == [
        "fd:Connectivity",
        "fd:Wifi",
        "fd:WifiOutage",
    ]
    assert search.concept_category(["fd:WifiOutage"], concepts) == "Connectivity"
