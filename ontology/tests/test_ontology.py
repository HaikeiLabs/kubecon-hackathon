"""Structural tests for the friction vocabulary and its compiled artifacts.

Run: uv run --with rdflib --with pytest pytest ontology/tests -q
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ONTOLOGY_DIR = Path(__file__).resolve().parents[1]
BUILD = ONTOLOGY_DIR / "build"

TOPS = {
    "fd:Venue",
    "fd:Accessibility",
    "fd:Schedule",
    "fd:Connectivity",
    "fd:FoodAndBeverage",
    "fd:Registration",
    "fd:Content",
    "fd:SafetyAndConduct",
    "fd:Transport",
    "fd:SponsorsAndExpo",
    "fd:Comfort",
}
FIELDS = [
    "id",
    "iri",
    "pref_label",
    "alt_labels",
    "definition",
    "broader",
    "ancestors",
    "path",
    "related",
    "top_concept",
]


def _load_compiler():
    spec = importlib.util.spec_from_file_location(
        "friction_compile", ONTOLOGY_DIR / "compile.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compiler = _load_compiler()


@pytest.fixture(scope="module")
def concepts() -> list[dict]:
    return compiler.build_concepts(compiler.load_graph())


@pytest.fixture(scope="module")
def by_id(concepts) -> dict[str, dict]:
    return {c["id"]: c for c in concepts}


def test_all_eleven_tops_present_and_parentless(by_id):
    tops = {cid for cid, c in by_id.items() if not c["broader"]}
    assert tops == TOPS
    for top in TOPS:
        assert by_id[top]["top_concept"] == top
        assert by_id[top]["path"] == top.removeprefix("fd:")


def test_ids_unique_and_curies(concepts):
    ids = [c["id"] for c in concepts]
    assert len(ids) == len(set(ids))
    for c in concepts:
        assert re.fullmatch(r"fd:[A-Z][A-Za-z]+", c["id"])
        assert c["iri"] == "https://haikei.dev/ontology/friction#" + c["id"][3:]


def test_record_shape(concepts):
    assert concepts == sorted(concepts, key=lambda c: c["id"])
    for c in concepts:
        assert list(c) == FIELDS


def test_every_concept_has_label_definition_and_broader(concepts):
    for c in concepts:
        assert c["pref_label"].strip(), c["id"]
        assert c["definition"].strip(), c["id"]
        if c["id"] not in TOPS:
            assert c["broader"], f"{c['id']} has no broader"


def test_references_resolve(by_id):
    for c in by_id.values():
        for ref in c["broader"] + c["related"] + c["ancestors"] + [c["top_concept"]]:
            assert ref in by_id, f"{c['id']} -> {ref}"


def test_ancestors_are_transitive_closure(by_id):
    def closure(cid: str) -> set[str]:
        out: set[str] = set()
        frontier = list(by_id[cid]["broader"])
        while frontier:
            node = frontier.pop()
            if node not in out:
                out.add(node)
                frontier.extend(by_id[node]["broader"])
        return out

    for cid, c in by_id.items():
        assert cid not in c["ancestors"]
        assert set(c["ancestors"]) == closure(cid)
        assert c["top_concept"] in set(c["ancestors"]) | {cid}
        assert c["path"].split("/")[0] == c["top_concept"][3:]
        assert c["path"].split("/")[-1] == cid[3:]


def test_depth_is_at_most_three_levels(concepts):
    assert max(c["path"].count("/") for c in concepts) <= 2


def test_no_broader_cycles_detected():
    with pytest.raises(compiler.OntologyError, match="cycle"):
        compiler._ancestors(
            "fd:A", {"fd:A": ["fd:B"], "fd:B": ["fd:C"], "fd:C": ["fd:A"]}
        )


def test_labels_do_not_collide_across_concepts(concepts):
    owner: dict[str, str] = {}
    for c in concepts:
        for label in {
            compiler._clean_term(x) for x in [c["pref_label"], *c["alt_labels"]]
        }:
            assert label not in owner, (
                f"{label!r} used by {owner.get(label)} and {c['id']}"
            )
            owner[label] = c["id"]


def test_synonyms_format(concepts):
    rules = compiler.build_synonyms(concepts)
    assert [r["id"] for r in rules] == [c["id"] for c in concepts]
    for r in rules:
        assert list(r) == ["id", "synonyms"]
        assert r["synonyms"] == r["synonyms"].lower()
        assert "=>" not in r["synonyms"]
        terms = r["synonyms"].split(", ")
        assert all(t and t == t.strip() for t in terms)
        assert len(terms) == len(set(terms))


def test_compile_is_deterministic_and_matches_committed(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    compiler.compile_ontology(build_dir=first)
    compiler.compile_ontology(build_dir=second)
    for name in ("concepts.json", "synonyms.json"):
        a = (first / name).read_bytes()
        assert a == (second / name).read_bytes()
        assert a == (BUILD / name).read_bytes(), f"{name} is stale; rerun compile.py"


def test_committed_artifacts_parse():
    concepts = json.loads((BUILD / "concepts.json").read_text())
    synonyms = json.loads((BUILD / "synonyms.json").read_text())
    assert len(concepts) == len(synonyms) >= 80
