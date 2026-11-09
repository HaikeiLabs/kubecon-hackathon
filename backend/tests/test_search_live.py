"""Live smoke test against the Elastic project. Run: pytest -m live -s tests/test_search_live.py

Skipped unless ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY are set. Creates the v2 indices
if missing, loads concepts (real ontology build if present, else the fixture), indexes a
throwaway bucket, retrieves it, then deletes it. Never touches v1 indices.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app import search

FIXTURE = Path(__file__).parent / "fixtures" / "concepts.sample.json"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.getenv("ELASTICSEARCH_URL") and os.getenv("ELASTICSEARCH_API_KEY")),
        reason="needs ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY",
    ),
]


def test_live_smoke() -> None:
    from elasticsearch import Elasticsearch

    client = Elasticsearch(
        os.environ["ELASTICSEARCH_URL"], api_key=os.environ["ELASTICSEARCH_API_KEY"]
    )
    concepts_file = search.default_concepts_path()
    if not concepts_file.is_file():
        concepts_file = FIXTURE
    concepts = search.read_concepts(concepts_file)
    bucket_id = None
    try:
        search.ensure_indices(client)
        loaded = search.load_concepts(client, concepts_file)

        tags = search.link_concepts(
            client, "wi-fi down near hall B, no internet", concepts=concepts
        )
        concept_ids = [t.concept_id for t in tags]
        bucket = search.create_bucket(
            client,
            f"Smoke test Wi-Fi outage {uuid4().hex[:6]}",
            "Attendees in Hall B cannot get online; the wireless network keeps dropping.",
            concept_ids,
            concepts=concepts,
        )
        bucket_id = bucket.id
        results = search.search_candidate_buckets(
            client, "wifi not working in hall b", concept_ids, k=5, concepts=concepts
        )
        ids = [r.bucket.id for r in results]
        print(
            f"LIVE SMOKE OK concepts_loaded={loaded} tags={concept_ids} "
            f"bucket_rank={ids.index(bucket_id) + 1 if bucket_id in ids else None}/{len(ids)}"
        )
        assert tags, "expected at least one concept tag"
        assert bucket_id in ids
    finally:
        if bucket_id:
            client.delete(index=search.BUCKETS_INDEX, id=bucket_id, refresh=True)
        client.close()
