"""Elasticsearch boundary for concepts, reports, and issue buckets.

Plain functions that take an Elasticsearch client so the triage agent can wrap them as
governed tools. Pure helpers (exact concept matcher, mapping and query builders) are kept
separate so they are unit-testable without a cluster.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from elastic_transport import TransportError
from elasticsearch.exceptions import ApiError, NotFoundError

from app.models import Bucket, BucketSearchResult, ConceptTag, Report

logger = logging.getLogger(__name__)

CONCEPTS_INDEX = "friction-desk-concepts-v1"
REPORTS_INDEX = "friction-desk-reports-v2"
BUCKETS_INDEX = "friction-desk-buckets-v2"
SYNONYMS_SET = "friction-desk-concepts"
SEMANTIC_FIELD = "semantic"

EXACT_CONFIDENCE = 0.95
HYBRID_MIN_NORMALIZED_SCORE = 0.6
HYBRID_CANDIDATES = 10
MAX_CONCEPT_TAGS = 5

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONCEPTS_PATH = BACKEND_DIR.parent / "ontology" / "build" / "concepts.json"
DEFAULT_SEED_DIR = BACKEND_DIR / "seed"

Concept = dict[str, Any]


# --------------------------------------------------------------------------- concepts


def default_concepts_path() -> Path:
    return Path(os.getenv("FD_CONCEPTS_PATH") or DEFAULT_CONCEPTS_PATH)


def read_concepts(path: Path | str | None = None) -> list[Concept]:
    """Read the compiled ontology; an absent file yields no concepts rather than an error."""
    return list(_read_concepts_cached(str(path or default_concepts_path())))


@lru_cache(maxsize=8)
def _read_concepts_cached(path: str) -> tuple[Concept, ...]:
    file = Path(path)
    if not file.is_file():
        logger.warning("concepts file not found: %s", file)
        return ()
    return tuple(json.loads(file.read_text()))


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.lower()).split())


def _labels(concept: Concept) -> list[str]:
    return [concept["pref_label"], *concept.get("alt_labels", [])]


def exact_concept_matches(text: str, concepts: Sequence[Concept]) -> list[ConceptTag]:
    """Pass 1: word-boundary phrase match of pref/alt labels (case and punctuation folded).

    When both a concept and one of its ancestors match, only the more specific concept is
    kept; ancestors are carried separately by `concept_closure`.
    """
    haystack = f" {_normalize(text)} "
    matched: dict[str, Concept] = {}
    for concept in concepts:
        for label in _labels(concept):
            needle = _normalize(label)
            if needle and f" {needle} " in haystack:
                matched[concept["id"]] = concept
                break
    implied = {ancestor for c in matched.values() for ancestor in c.get("ancestors", [])}
    return [
        ConceptTag(
            concept_id=c["id"], label=c["pref_label"], confidence=EXACT_CONFIDENCE, method="exact"
        )
        for cid, c in sorted(matched.items())
        if cid not in implied
    ]


def concept_closure(concept_ids: Iterable[str], concepts: Sequence[Concept]) -> list[str]:
    """The given concepts plus all their transitive broader concepts, sorted."""
    by_id = {c["id"]: c for c in concepts}
    closure: set[str] = set()
    for cid in concept_ids:
        closure.add(cid)
        closure.update(by_id.get(cid, {}).get("ancestors", []))
    return sorted(closure)


def concept_category(concept_ids: Sequence[str], concepts: Sequence[Concept]) -> str | None:
    """Pref label of the top concept of the first known concept id."""
    by_id = {c["id"]: c for c in concepts}
    for cid in concept_ids:
        concept = by_id.get(cid)
        if concept:
            top = by_id.get(concept.get("top_concept") or cid)
            return (top or concept)["pref_label"]
    return None


def synonym_rules(concepts: Sequence[Concept]) -> list[dict[str, str]]:
    """Elastic synonym-set rules: one comma-equivalence rule per concept with 2+ labels."""
    rules = []
    for concept in concepts:
        labels: list[str] = []
        for label in _labels(concept):
            cleaned = " ".join(label.replace(",", " ").lower().split())
            if cleaned and cleaned not in labels:
                labels.append(cleaned)
        if len(labels) > 1:
            rules.append({"id": _rule_id(concept["id"]), "synonyms": ", ".join(labels)})
    return rules


def _rule_id(concept_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", concept_id)


def _read_synonym_rules(path: Path, concepts: Sequence[Concept]) -> list[dict[str, str]]:
    compiled = path.with_name("synonyms.json")
    if compiled.is_file():
        rules = json.loads(compiled.read_text())
        return [{"id": _rule_id(r["id"]), "synonyms": r["synonyms"]} for r in rules]
    return synonym_rules(concepts)


# --------------------------------------------------------------------------- mappings


def _text(**extra: Any) -> dict[str, Any]:
    return {"type": "text", "analyzer": "fd_text_index", "search_analyzer": "fd_text", **extra}


def _keyword_text(**extra: Any) -> dict[str, Any]:
    return _text(fields={"keyword": {"type": "keyword"}}, **extra)


ANALYSIS_SETTINGS: dict[str, Any] = {
    "analysis": {
        "filter": {
            "fd_synonyms": {
                "type": "synonym_graph",
                "synonyms_set": SYNONYMS_SET,
                "updateable": True,
            },
            "fd_english_stemmer": {"type": "stemmer", "language": "english"},
        },
        "analyzer": {
            # Index-time chain; synonyms are applied only at search time so the set can be
            # updated without reindexing.
            "fd_text_index": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding", "fd_english_stemmer"],
            },
            "fd_text": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding", "fd_synonyms", "fd_english_stemmer"],
            },
        },
    }
}


def index_definitions() -> dict[str, dict[str, Any]]:
    """Index bodies (settings + mappings). Serverless: no shard/replica settings."""
    semantic = {"type": "semantic_text"}
    concept_fields = {
        "concept_ids": {"type": "keyword"},
        "concept_ancestors": {"type": "keyword"},
    }
    return {
        CONCEPTS_INDEX: {
            "settings": ANALYSIS_SETTINGS,
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "iri": {"type": "keyword"},
                    "pref_label": _keyword_text(copy_to=[SEMANTIC_FIELD]),
                    "alt_labels": _text(),
                    "definition": _text(copy_to=[SEMANTIC_FIELD]),
                    "broader": {"type": "keyword"},
                    "ancestors": {"type": "keyword"},
                    "related": {"type": "keyword"},
                    "path": {"type": "keyword"},
                    "top_concept": {"type": "keyword"},
                    SEMANTIC_FIELD: semantic,
                }
            },
        },
        REPORTS_INDEX: {
            "settings": ANALYSIS_SETTINGS,
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "description": _text(copy_to=[SEMANTIC_FIELD]),
                    "location": _keyword_text(),
                    "created_at": {"type": "date"},
                    "status": {"type": "keyword"},
                    "bucket_id": {"type": "keyword"},
                    "concept_tags": {"type": "object", "enabled": False},
                    "triage": {"type": "object", "enabled": False},
                    **concept_fields,
                    SEMANTIC_FIELD: semantic,
                }
            },
        },
        BUCKETS_INDEX: {
            "settings": ANALYSIS_SETTINGS,
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": _keyword_text(copy_to=[SEMANTIC_FIELD]),
                    "summary": _text(copy_to=[SEMANTIC_FIELD]),
                    "status": {"type": "keyword"},
                    "report_count": {"type": "integer"},
                    "updated_at": {"type": "date"},
                    "category": {"type": "keyword"},
                    **concept_fields,
                    SEMANTIC_FIELD: semantic,
                }
            },
        },
    }


def ensure_synonyms_set(client: Any) -> None:
    """The analyzers reference the synonyms set, so it must exist before index creation."""
    try:
        client.synonyms.get_synonym(id=SYNONYMS_SET)
    except NotFoundError:
        client.synonyms.put_synonym(id=SYNONYMS_SET, synonyms_set=[])


def ensure_indices(client: Any) -> None:
    ensure_synonyms_set(client)
    for name, body in index_definitions().items():
        if not client.indices.exists(index=name):
            client.indices.create(index=name, **body)


def load_concepts(client: Any, concepts_path: Path | str | None = None) -> int:
    """Index the compiled ontology and publish its synonyms set. Returns concepts indexed."""
    path = Path(concepts_path or default_concepts_path())
    concepts = read_concepts(path)
    if not concepts:
        return 0
    client.synonyms.put_synonym(id=SYNONYMS_SET, synonyms_set=_read_synonym_rules(path, concepts))
    operations: list[dict[str, Any]] = []
    for concept in concepts:
        operations.append({"index": {"_index": CONCEPTS_INDEX, "_id": concept["id"]}})
        operations.append(concept)
    result = client.bulk(operations=operations, refresh=True)
    if result.get("errors"):
        failed = [i for i in result["items"] if i.get("index", {}).get("error")]
        raise RuntimeError(f"{len(failed)} concepts failed to index: {failed[:1]}")
    return len(concepts)


# --------------------------------------------------------------------------- queries


def build_concept_search_body(text: str, size: int = HYBRID_CANDIDATES) -> dict[str, Any]:
    return {
        "size": size,
        "_source": ["id", "pref_label"],
        "retriever": {
            "rrf": {
                "retrievers": [
                    {
                        "standard": {
                            "query": {
                                "multi_match": {
                                    "query": text,
                                    "fields": ["pref_label^3", "alt_labels^2", "definition"],
                                }
                            }
                        }
                    },
                    {"standard": {"query": {"semantic": {"field": SEMANTIC_FIELD, "query": text}}}},
                ],
                "rank_window_size": 50,
            }
        },
    }


def build_bucket_search_body(
    text: str, concept_ancestors: Sequence[str], k: int = 5
) -> dict[str, Any]:
    """RRF of (lexical w/ search-time synonyms + concept-overlap boost) and semantic_text."""
    open_only = [{"term": {"status": "open"}}]
    lexical: dict[str, Any] = {
        "bool": {
            "should": [{"multi_match": {"query": text, "fields": ["title^2", "summary"]}}],
            "filter": open_only,
            "minimum_should_match": 1,
        }
    }
    if concept_ancestors:
        lexical["bool"]["should"].append(
            {"terms": {"concept_ancestors": list(concept_ancestors), "boost": 2.0}}
        )
    semantic = {
        "bool": {
            "must": [{"semantic": {"field": SEMANTIC_FIELD, "query": text}}],
            "filter": open_only,
        }
    }
    return {
        "size": k,
        "_source": {"excludes": [SEMANTIC_FIELD]},
        "retriever": {
            "rrf": {
                "retrievers": [{"standard": {"query": lexical}}, {"standard": {"query": semantic}}],
                "rank_window_size": max(50, k),
            }
        },
    }


def _hybrid_concept_matches(client: Any, text: str) -> list[ConceptTag]:
    try:
        result = client.search(index=CONCEPTS_INDEX, **build_concept_search_body(text))
    except (ApiError, TransportError) as exc:
        logger.warning("hybrid concept search failed: %s", exc)
        return []
    hits = result["hits"]["hits"]
    if not hits:
        return []
    top = hits[0]["_score"] or 1.0
    tags = []
    for hit in hits:
        normalized = (hit["_score"] or 0.0) / top
        if normalized >= HYBRID_MIN_NORMALIZED_SCORE:
            tags.append(
                ConceptTag(
                    concept_id=hit["_source"]["id"],
                    label=hit["_source"]["pref_label"],
                    confidence=round(min(0.9, 0.9 * normalized), 3),
                    method="hybrid",
                )
            )
    return tags


def link_concepts(
    client: Any, text: str, *, concepts: Sequence[Concept] | None = None
) -> list[ConceptTag]:
    """Link free text to ontology concepts: exact label matches, then hybrid search."""
    concepts = read_concepts() if concepts is None else concepts
    tags = exact_concept_matches(text, concepts)
    if client is not None and len(tags) < MAX_CONCEPT_TAGS:
        exact_ids = {t.concept_id for t in tags}
        implied = set(concept_closure(exact_ids, concepts))
        for tag in _hybrid_concept_matches(client, text):
            if tag.concept_id not in implied:
                tags.append(tag)
                implied.add(tag.concept_id)
    return tags[:MAX_CONCEPT_TAGS]


def search_candidate_buckets(
    client: Any,
    text: str,
    concept_ids: Sequence[str],
    k: int = 5,
    *,
    concepts: Sequence[Concept] | None = None,
) -> list[BucketSearchResult]:
    concepts = read_concepts() if concepts is None else concepts
    body = build_bucket_search_body(text, concept_closure(concept_ids, concepts), k)
    result = client.search(index=BUCKETS_INDEX, **body)
    return [
        BucketSearchResult(bucket=Bucket.model_validate(hit["_source"]), score=hit["_score"] or 0.0)
        for hit in result["hits"]["hits"]
    ]


# --------------------------------------------------------------------------- documents


def apply_concept_tags(
    report: Report, tags: Sequence[ConceptTag], concepts: Sequence[Concept] | None = None
) -> Report:
    concepts = read_concepts() if concepts is None else concepts
    ids = [t.concept_id for t in tags]
    return report.model_copy(
        update={
            "concept_tags": list(tags),
            "concept_ids": ids,
            "concept_ancestors": concept_closure(ids, concepts),
        }
    )


def index_report(client: Any, report: Report) -> Report:
    client.index(
        index=REPORTS_INDEX, id=report.id, document=report.model_dump(mode="json"), refresh=True
    )
    return report


def get_report(client: Any, report_id: str) -> Report | None:
    try:
        return Report.model_validate(client.get(index=REPORTS_INDEX, id=report_id)["_source"])
    except NotFoundError:
        return None


def get_bucket(client: Any, bucket_id: str) -> Bucket | None:
    try:
        return Bucket.model_validate(client.get(index=BUCKETS_INDEX, id=bucket_id)["_source"])
    except NotFoundError:
        return None


def index_bucket(client: Any, bucket: Bucket) -> Bucket:
    client.index(
        index=BUCKETS_INDEX, id=bucket.id, document=bucket.model_dump(mode="json"), refresh=True
    )
    return bucket


def create_bucket(
    client: Any,
    title: str,
    summary: str,
    concept_ids: Sequence[str],
    *,
    concepts: Sequence[Concept] | None = None,
) -> Bucket:
    concepts = read_concepts() if concepts is None else concepts
    bucket = Bucket(
        id=str(uuid4()),
        title=title,
        summary=summary,
        updated_at=datetime.now(UTC),
        concept_ids=list(concept_ids),
        concept_ancestors=concept_closure(concept_ids, concepts),
        category=concept_category(concept_ids, concepts),
    )
    return index_bucket(client, bucket)


def assign_report(
    client: Any,
    report_id: str,
    bucket_id: str,
    *,
    concepts: Sequence[Concept] | None = None,
) -> Report:
    """Confirm a report into a bucket, folding its concepts into the bucket."""
    concepts = read_concepts() if concepts is None else concepts
    report = get_report(client, report_id)
    if report is None:
        raise LookupError(f"report {report_id} not found")
    bucket = get_bucket(client, bucket_id)
    if bucket is None:
        raise LookupError(f"bucket {bucket_id} not found")

    already_counted = report.status == "confirmed" and report.bucket_id == bucket_id
    concept_ids = list(dict.fromkeys([*bucket.concept_ids, *report.concept_ids]))
    bucket = bucket.model_copy(
        update={
            "report_count": bucket.report_count + (0 if already_counted else 1),
            "updated_at": datetime.now(UTC),
            "concept_ids": concept_ids,
            "concept_ancestors": concept_closure(concept_ids, concepts),
            "category": bucket.category or concept_category(concept_ids, concepts),
        }
    )
    report = report.model_copy(update={"bucket_id": bucket_id, "status": "confirmed"})
    index_bucket(client, bucket)
    return index_report(client, report)


def _read_seed(seed_dir: Path, name: str) -> list[dict[str, Any]]:
    file = seed_dir / name
    if not file.is_file():
        logger.warning("seed file not found: %s", file)
        return []
    return json.loads(file.read_text())


def reset_and_seed(
    client: Any,
    seed_dir: Path | str | None = None,
    *,
    concepts_path: Path | str | None = None,
) -> dict[str, int]:
    """Drop and recreate the v2 indices, then load concepts and seed data.

    Only touches the v2 report/bucket indices and the concepts index; never v1 data.
    Missing seed or ontology files are tolerated.
    """
    seed_path = Path(seed_dir or DEFAULT_SEED_DIR)
    for index in (REPORTS_INDEX, BUCKETS_INDEX, CONCEPTS_INDEX):
        client.indices.delete(index=index, ignore_unavailable=True)
    ensure_indices(client)
    concepts_file = Path(concepts_path or default_concepts_path())
    concepts = read_concepts(concepts_file)
    loaded = load_concepts(client, concepts_file)

    now = datetime.now(UTC)
    buckets = 0
    for raw in _read_seed(seed_path, "buckets.json"):
        ids = list(raw.get("concept_ids", []))
        bucket = Bucket.model_validate(
            {
                "updated_at": now,
                **raw,
                "concept_ancestors": concept_closure(ids, concepts),
                "category": raw.get("category") or concept_category(ids, concepts),
            }
        )
        index_bucket(client, bucket)
        buckets += 1

    reports = 0
    for raw in _read_seed(seed_path, "reports.json"):
        report = Report.model_validate({"id": str(uuid4()), "created_at": now, **raw})
        if not report.concept_tags:
            tags = link_concepts(client, report.description, concepts=concepts)
            report = apply_concept_tags(report, tags, concepts)
        else:
            report = apply_concept_tags(report, report.concept_tags, concepts)
        index_report(client, report)
        reports += 1

    return {"concepts": loaded, "buckets": buckets, "reports": reports}
