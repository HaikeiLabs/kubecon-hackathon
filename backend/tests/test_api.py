from fastapi.testclient import TestClient

from app import main
from app.main import BUCKETS_INDEX, REPORTS_INDEX, app


class FakeIndices:
    def __init__(self) -> None:
        self.created: dict[str, dict] = {}

    def exists(self, *, index: str) -> bool:
        return index in self.created

    def create(self, *, index: str, mappings: dict) -> None:
        self.created[index] = mappings


class FakeElasticsearch:
    def __init__(self, *args, **kwargs) -> None:
        self.indices = FakeIndices()
        self.documents: dict[str, dict[str, dict]] = {REPORTS_INDEX: {}, BUCKETS_INDEX: {}}

    def ping(self) -> bool:
        return True

    def index(self, *, index: str, id: str, document: dict) -> None:
        self.documents[index][id] = document

    def search(self, *, index: str, **kwargs) -> dict:
        docs = list(self.documents[index].values())
        if index == BUCKETS_INDEX:
            docs = [doc for doc in docs if doc.get("status") == "open"]
        return {
            "hits": {
                "hits": [{"_source": doc, "_score": 1.25} for doc in docs],
            }
        }

    def close(self) -> None:
        pass


def test_report_submission_and_listing_are_anonymous(monkeypatch) -> None:
    monkeypatch.setattr(main, "Elasticsearch", FakeElasticsearch)

    with TestClient(app) as client:
        response = client.post(
            "/api/reports",
            json={"description": "The accessible entrance is blocked", "location": "Hall B"},
        )
        assert response.status_code == 201
        report = response.json()
        assert report["status"] == "untriaged"
        assert "email" not in report

        listed = client.get("/api/reports")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == report["id"]

        invalid = client.post(
            "/api/reports",
            json={"description": "The accessible entrance is blocked", "email": "a@b.test"},
        )
        assert invalid.status_code == 422


def test_bucket_search_returns_open_candidates(monkeypatch) -> None:
    monkeypatch.setattr(main, "Elasticsearch", FakeElasticsearch)

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
        response = client.get("/api/buckets/search", params={"q": "entrance blocked"})

    assert response.status_code == 200
    assert response.json()[0]["bucket"]["id"] == "bucket-1"
    assert response.json()[0]["score"] == 1.25
