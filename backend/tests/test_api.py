import json
import sys
from pathlib import Path

import pytest
from elasticsearch.exceptions import NotFoundError
from fastapi.testclient import TestClient

from app import main, search
from app.main import app
from app.models import TriageResult
from app.search import BUCKETS_INDEX, CONCEPTS_INDEX, REPORTS_INDEX

FIXTURE = Path(__file__).parent / "fixtures" / "concepts.sample.json"


def _not_found() -> NotFoundError:
    return NotFoundError("not found", meta=None, body={})  # type: ignore[arg-type]


class FakeIndices:
    def __init__(self, store: dict[str, dict[str, dict]]) -> None:
        self.store = store
        self.created: dict[str, dict] = {}

    def exists(self, *, index: str) -> bool:
        return index in self.created

    def create(self, *, index: str, settings: dict, mappings: dict) -> None:
        self.created[index] = {"settings": settings, "mappings": mappings}
        self.store.setdefault(index, {})

    def delete(self, *, index: str, ignore_unavailable: bool = False) -> None:
        self.created.pop(index, None)
        self.store.pop(index, None)


class FakeSynonyms:
    def __init__(self) -> None:
        self.sets: dict[str, list[dict]] = {}

    def get_synonym(self, *, id: str) -> dict:
        if id not in self.sets:
            raise _not_found()
        return {"synonyms_set": self.sets[id]}

    def put_synonym(self, *, id: str, synonyms_set: list[dict]) -> None:
        self.sets[id] = synonyms_set


class FakeElasticsearch:
    """In-memory stand-in: every search returns all docs, open-only for buckets."""

    def __init__(self, *args, **kwargs) -> None:
        self.documents: dict[str, dict[str, dict]] = {}
        self.indices = FakeIndices(self.documents)
        self.synonyms = FakeSynonyms()
        self.searches: list[dict] = []

    def ping(self) -> bool:
        return True

    def index(self, *, index: str, id: str, document: dict, refresh: bool = False) -> None:
        self.documents.setdefault(index, {})[id] = document

    def get(self, *, index: str, id: str) -> dict:
        try:
            return {"_source": self.documents[index][id]}
        except KeyError:
            raise _not_found() from None

    def bulk(self, *, operations: list[dict], refresh: bool = False) -> dict:
        for action, doc in zip(operations[::2], operations[1::2], strict=True):
            meta = action["index"]
            self.index(index=meta["_index"], id=meta["_id"], document=doc)
        return {"errors": False, "items": []}

    def search(self, *, index: str, **kwargs) -> dict:
        self.searches.append({"index": index, **kwargs})
        if index == CONCEPTS_INDEX:
            return {"hits": {"hits": []}}
        docs = list(self.documents.get(index, {}).values())
        if index == BUCKETS_INDEX:
            docs = [doc for doc in docs if doc.get("status") == "open"]
        return {"hits": {"hits": [{"_source": doc, "_score": 1.25} for doc in docs]}}

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def fake_env(monkeypatch) -> None:
    monkeypatch.setattr(main, "Elasticsearch", FakeElasticsearch)
    monkeypatch.setenv("FD_CONCEPTS_PATH", str(FIXTURE))
    monkeypatch.setitem(sys.modules, "app.triage.service", None)  # triage not installed


def test_startup_creates_v2_indices_and_synonyms_set() -> None:
    with TestClient(app):
        fake_es = app.state.elasticsearch
        assert set(fake_es.indices.created) == {CONCEPTS_INDEX, REPORTS_INDEX, BUCKETS_INDEX}
        assert search.SYNONYMS_SET in fake_es.synonyms.sets


def test_report_submission_links_concepts_without_triage() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/reports", json={"description": "Wi-Fi down in Hall B", "location": "Hall B"}
        )
        assert response.status_code == 201
        report = response.json()
        assert report["status"] == "untriaged"
        assert report["triage"] is None
        assert "email" not in report
        assert report["concept_ids"] == ["fd:WifiOutage"]
        assert report["concept_ancestors"] == ["fd:Connectivity", "fd:Wifi", "fd:WifiOutage"]
        assert report["concept_tags"][0]["method"] == "exact"

        stored = app.state.elasticsearch.documents[REPORTS_INDEX][report["id"]]
        assert stored["concept_ids"] == ["fd:WifiOutage"]

        listed = client.get("/api/reports")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == report["id"]

        detail = client.get(f"/api/reports/{report['id']}")
        assert detail.status_code == 200
        assert detail.json()["id"] == report["id"]
        assert client.get("/api/reports/missing").status_code == 404

        invalid = client.post(
            "/api/reports",
            json={"description": "The accessible entrance is blocked", "email": "a@b.test"},
        )
        assert invalid.status_code == 422


def test_report_submission_calls_triage_when_available(monkeypatch) -> None:
    calls = []

    def fake_triage(client, report):
        calls.append(report.id)
        return TriageResult(
            disposition="new_bucket",
            proposed_title="Wi-Fi outage",
            confidence=0.5,
            rationale="no candidates",
            concept_ids=report.concept_ids,
            extractor_version="test",
        )

    module = type(sys)("app.triage.service")
    module.triage_report = fake_triage
    monkeypatch.setitem(sys.modules, "app.triage.service", module)

    with TestClient(app) as client:
        response = client.post("/api/reports", json={"description": "no internet in room 3"})

    assert response.status_code == 201
    body = response.json()
    assert calls == [body["id"]]
    assert body["status"] == "proposed"
    assert body["triage"]["disposition"] == "new_bucket"


def test_bucket_search_returns_open_candidates_with_rrf() -> None:
    with TestClient(app) as client:
        fake_es = app.state.elasticsearch
        fake_es.index(
            index=BUCKETS_INDEX,
            id="bucket-1",
            document={
                "id": "bucket-1",
                "title": "Blocked accessible entrance",
                "summary": "The step-free entrance is blocked.",
                "status": "open",
                "report_count": 2,
                "updated_at": "2026-11-09T12:00:00Z",
            },
        )
        response = client.get("/api/buckets/search", params={"q": "ramp blocked"})

    assert response.status_code == 200
    assert response.json()[0]["bucket"]["id"] == "bucket-1"
    assert response.json()[0]["score"] == 1.25
    bucket_search = [s for s in fake_es.searches if s["index"] == BUCKETS_INDEX][-1]
    lexical = bucket_search["retriever"]["rrf"]["retrievers"][0]["standard"]["query"]["bool"]
    assert lexical["should"][1]["terms"]["concept_ancestors"] == [
        "fd:Accessibility",
        "fd:BlockedStepFreeAccess",
        "fd:StepFreeAccess",
    ]


def test_admin_reset_seeds_buckets_and_reports(tmp_path, monkeypatch) -> None:
    (tmp_path / "buckets.json").write_text(
        json.dumps(
            [
                {
                    "id": "wifi",
                    "title": "Wi-Fi outage",
                    "summary": "Hall B wifi",
                    "concept_ids": ["fd:WifiOutage"],
                }
            ]
        )
    )
    (tmp_path / "reports.json").write_text(json.dumps([{"description": "wifi down again"}]))
    monkeypatch.setenv("FD_SEED_DIR", str(tmp_path))

    with TestClient(app) as client:
        fake_es = app.state.elasticsearch
        fake_es.index(index=REPORTS_INDEX, id="stale", document={"id": "stale"})
        response = client.post("/api/admin/reset")

    assert response.status_code == 200
    assert response.json() == {"concepts": 6, "buckets": 1, "reports": 1}
    assert "stale" not in fake_es.documents[REPORTS_INDEX]
    bucket = fake_es.documents[BUCKETS_INDEX]["wifi"]
    assert bucket["category"] == "Connectivity"
    assert bucket["concept_ancestors"] == ["fd:Connectivity", "fd:Wifi", "fd:WifiOutage"]
    assert len(fake_es.documents[CONCEPTS_INDEX]) == 6
    assert fake_es.synonyms.sets[search.SYNONYMS_SET]


def test_admin_reset_tolerates_missing_seed_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FD_SEED_DIR", str(tmp_path / "nope"))

    with TestClient(app) as client:
        response = client.post("/api/admin/reset")

    assert response.status_code == 200
    assert response.json() == {"concepts": 6, "buckets": 0, "reports": 0}


def test_create_and_assign_report_updates_bucket() -> None:
    with TestClient(app):
        fake_es = app.state.elasticsearch
        concepts = search.read_concepts(FIXTURE)
        bucket = search.create_bucket(
            fake_es, "Wi-Fi outage", "Hall B", ["fd:WifiOutage"], concepts=concepts
        )
        assert bucket.category == "Connectivity"
        report = search.apply_concept_tags(
            main.Report(id="r1", description="ramp blocked", created_at="2026-11-09T12:00:00Z"),
            search.exact_concept_matches("ramp blocked", concepts),
            concepts,
        )
        search.index_report(fake_es, report)

        assigned = search.assign_report(fake_es, "r1", bucket.id, concepts=concepts)
        again = search.assign_report(fake_es, "r1", bucket.id, concepts=concepts)

        assert assigned.status == "confirmed" and assigned.bucket_id == bucket.id
        assert again.bucket_id == bucket.id
        stored = search.get_bucket(fake_es, bucket.id)
        assert stored is not None
        assert stored.report_count == 1
        assert set(stored.concept_ids) == {"fd:WifiOutage", "fd:BlockedStepFreeAccess"}
        with pytest.raises(LookupError):
            search.assign_report(fake_es, "missing", bucket.id, concepts=concepts)
