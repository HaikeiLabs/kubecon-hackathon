"""Compile the friction SKOS vocabulary into Elastic-ready JSON artifacts.

Usage: uv run --with rdflib python ontology/compile.py

Reads ontology/friction.ttl and writes (deterministically):
  ontology/build/concepts.json  -- one record per concept, sorted by id
  ontology/build/synonyms.json  -- Elastic synonyms-set rules, sorted by id
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, SKOS

FD = Namespace("https://haikei.dev/ontology/friction#")
PREFIX = "fd:"
LANG = "en"

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "friction.ttl"
BUILD = ROOT / "build"


class OntologyError(ValueError):
    """The vocabulary violates a structural rule."""


def curie(iri: URIRef) -> str:
    text = str(iri)
    if not text.startswith(str(FD)):
        raise OntologyError(f"concept outside fd namespace: {text}")
    return PREFIX + text[len(str(FD)) :]


def load_graph(path: Path = SOURCE) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def _literal(graph: Graph, node: URIRef, prop: URIRef) -> str | None:
    values = sorted(
        str(v)
        for v in graph.objects(node, prop)
        if getattr(v, "language", LANG) in (LANG, None)
    )
    return values[0] if values else None


def _ids(graph: Graph, node: URIRef, prop: URIRef) -> list[str]:
    return sorted(curie(v) for v in graph.objects(node, prop) if isinstance(v, URIRef))


def _ancestors(concept_id: str, broader: dict[str, list[str]]) -> list[str]:
    """Transitive closure of skos:broader, excluding self; raises on cycles."""
    seen: set[str] = set()
    stack: list[tuple[str, tuple[str, ...]]] = [
        (parent, (concept_id,)) for parent in broader.get(concept_id, [])
    ]
    while stack:
        node, trail = stack.pop()
        if node in trail:
            raise OntologyError(f"broader cycle: {' -> '.join(trail + (node,))}")
        if node in seen:
            continue
        seen.add(node)
        stack.extend((parent, trail + (node,)) for parent in broader.get(node, []))
    return sorted(seen)


def _path(concept_id: str, broader: dict[str, list[str]]) -> str:
    """Slash path from top concept, following the first (sorted) broader."""
    parts = []
    node: str | None = concept_id
    while node is not None:
        parts.append(node[len(PREFIX) :])
        parents = broader.get(node, [])
        node = parents[0] if parents else None
    return "/".join(reversed(parts))


def build_concepts(graph: Graph) -> list[dict]:
    nodes = sorted(
        (n for n in graph.subjects(RDF.type, SKOS.Concept) if isinstance(n, URIRef)),
        key=str,
    )
    tops = {curie(n) for n in graph.subjects(SKOS.topConceptOf, None)}
    broader = {curie(n): _ids(graph, n, SKOS.broader) for n in nodes}
    known = set(broader)

    concepts = []
    for node in nodes:
        cid = curie(node)
        dangling = [
            b for b in broader[cid] + _ids(graph, node, SKOS.related) if b not in known
        ]
        if dangling:
            raise OntologyError(f"{cid} references unknown concepts: {dangling}")
        ancestors = _ancestors(cid, broader)
        roots = sorted(a for a in ancestors + [cid] if a in tops)
        if not roots:
            raise OntologyError(f"{cid} does not descend from a top concept")
        concepts.append(
            {
                "id": cid,
                "iri": str(node),
                "pref_label": _literal(graph, node, SKOS.prefLabel) or "",
                "alt_labels": sorted(
                    {str(v) for v in graph.objects(node, SKOS.altLabel)}
                ),
                "definition": _literal(graph, node, SKOS.definition) or "",
                "broader": broader[cid],
                "ancestors": ancestors,
                "path": _path(cid, broader),
                "related": _ids(graph, node, SKOS.related),
                "top_concept": roots[0],
            }
        )
    return sorted(concepts, key=lambda c: c["id"])


def _clean_term(label: str) -> str:
    # Commas separate equivalents in Elastic synonym rules; collapse whitespace.
    return " ".join(label.lower().replace(",", " ").split())


def build_synonyms(concepts: list[dict]) -> list[dict]:
    rules = []
    for concept in concepts:
        terms: list[str] = []
        for label in [concept["pref_label"], *concept["alt_labels"]]:
            term = _clean_term(label)
            if term and term not in terms:
                terms.append(term)
        rules.append({"id": concept["id"], "synonyms": ", ".join(terms)})
    return rules


def _dump(data: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def compile_ontology(source: Path = SOURCE, build_dir: Path = BUILD) -> list[dict]:
    concepts = build_concepts(load_graph(source))
    _dump(concepts, build_dir / "concepts.json")
    _dump(build_synonyms(concepts), build_dir / "synonyms.json")
    return concepts


def main() -> int:
    concepts = compile_ontology()
    print(f"wrote {len(concepts)} concepts to {BUILD.relative_to(ROOT.parent)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
