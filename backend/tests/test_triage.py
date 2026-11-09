from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from haikeilabs.agentware.middleware.types import CallerContext

from app.models import Bucket, BucketSearchResult, ConceptTag, Report
from app.triage import router as triage_router
from app.triage.llm import (
    Classification,
    ElasticInferenceClassifier,
    OpenAIClassifier,
    default_classifier,
)
from app.triage.policy import ROLE_ORGANIZER, ROLE_TRIAGE_AGENT, LocalPolicyEvaluator
from app.triage.service import triage_report
from app.triage.tools import (
    ASSIGN_REPORT,
    LINK_CONCEPTS,
    POLICY_RULES,
    PROPOSE_BUCKET,
    SEARCH_BUCKETS,
    Governor,
    build_registry,
    export_tool_manifest,
)

NOW = datetime(2026, 11, 9, tzinfo=UTC)
WIFI_TEXT = "The wifi in hall B keeps dropping during the keynote"


def bucket(bid: str, title: str, concepts: list[str]) -> Bucket:
    return Bucket(
        id=bid, title=title, summary=title, updated_at=NOW,
        concept_ids=concepts, concept_ancestors=["fd:Connectivity"] if "Wifi" in bid else [],
    )


class FakeBackend:
    """In-memory stand-in for app.search that records every mutation."""

    def __init__(self, tags=None, candidates=None):
        self.tags = tags if tags is not None else []
        self.candidates = candidates if candidates is not None else []
        self.reports = {
            "r1": Report(id="r1", description=WIFI_TEXT, created_at=NOW),
        }
        self.buckets: dict[str, Bucket] = {c.bucket.id: c.bucket for c in self.candidates}
        self.mutations: list[tuple] = []

    def link_concepts(self, client, text):
        return list(self.tags)

    def search_candidate_buckets(self, client, text, concept_ids, k=5):
        return list(self.candidates)[:k]

    def create_bucket(self, client, title, summary, concept_ids):
        self.mutations.append(("create_bucket", title))
        new = Bucket(id=f"b{len(self.buckets) + 1}", title=title, summary=summary,
                     updated_at=NOW, concept_ids=concept_ids)
        self.buckets[new.id] = new
        return new

    def assign_report(self, client, report_id, bucket_id):
        self.mutations.append(("assign_report", report_id, bucket_id))
        report = self.reports[report_id].model_copy(
            update={"bucket_id": bucket_id, "status": "confirmed"}
        )
        self.reports[report_id] = report
        return report

    def get_report(self, client, report_id):
        return self.reports.get(report_id)

    def index_report(self, client, report):
        self.reports[report.id] = report


WIFI_TAG = ConceptTag(concept_id="fd:WifiOutage", label="Wifi outage", confidence=0.9,
                      method="exact")
FOOD_TAG = ConceptTag(concept_id="fd:FoodQueue", label="Food queue", confidence=0.9,
                      method="exact")
WIFI_CAND = BucketSearchResult(bucket=bucket("bWifi", "Wifi drops", ["fd:WifiOutage"]),
                               score=2.0)
FOOD_CAND = BucketSearchResult(bucket=bucket("bFood", "Lunch lines", ["fd:FoodQueue"]),
                               score=1.0)


def governor() -> Governor:
    return Governor(evaluator=LocalPolicyEvaluator(POLICY_RULES))


def report(tags=()) -> Report:
    return Report(id="r1", description=WIFI_TEXT, created_at=NOW, concept_tags=list(tags))


class StubClassifier:
    version = "triage-v1:stub"

    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def classify(self, text, concepts, candidates):
        if self.error:
            raise self.error
        return self.result


# --- service: dispositions -------------------------------------------------------------


def test_confident_match_is_existing_bucket_and_never_assigns():
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND, FOOD_CAND])
    gov = governor()
    result = triage_report(None, report(), backend=backend, classifier=None, governor=gov)
    assert result.disposition == "existing_bucket"
    assert result.bucket_id == "bWifi"
    assert result.confidence >= 0.75
    assert result.concept_ids == ["fd:WifiOutage"]
    assert result.extractor_version == "fallback-v1"
    assert [e.tool for e in result.governance] == [LINK_CONCEPTS, SEARCH_BUCKETS]
    assert all(e.decision == "allow" for e in result.governance)
    assert backend.mutations == []


def test_distinct_report_proposes_new_bucket_without_mutation():
    backend = FakeBackend(tags=[FOOD_TAG], candidates=[WIFI_CAND])
    result = triage_report(None, report(), backend=backend, classifier=None, governor=governor())
    assert result.disposition == "new_bucket"
    assert result.bucket_id is None
    assert result.proposed_title == "Food queue reports"
    assert result.governance[-1].tool == PROPOSE_BUCKET
    assert result.governance[-1].decision == "allow"
    assert backend.mutations == []


def test_ambiguous_llm_choice_needs_review():
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND, FOOD_CAND])
    low = Classification(bucket_id="bWifi", confidence=0.5, rationale="maybe")
    result = triage_report(None, report(), backend=backend,
                           classifier=StubClassifier(low), governor=governor())
    assert result.disposition == "needs_review"
    assert result.bucket_id == "bWifi"
    assert result.extractor_version == "triage-v1:stub"
    assert backend.mutations == []


def test_llm_failure_falls_back_deterministically():
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND, FOOD_CAND])
    result = triage_report(None, report(), backend=backend,
                           classifier=StubClassifier(error=TimeoutError()), governor=governor())
    assert result.disposition == "existing_bucket"
    assert result.extractor_version == "triage-v1:stub|fallback-v1"


def test_openai_classifier_rejects_invented_bucket_and_falls_back():
    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["response_format"]["type"] == "json_schema"
            msg = type("M", (), {"content": '{"bucket_id":"invented","new_bucket_title":null,'
                                            '"new_bucket_summary":null,"confidence":0.99,'
                                            '"rationale":"x"}'})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    fake = type("O", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})})
    clf = OpenAIClassifier(model="m", client=fake)
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND])
    result = triage_report(None, report(), backend=backend, classifier=clf, governor=governor())
    assert result.extractor_version == "triage-v1:m|fallback-v1"
    assert result.bucket_id == "bWifi"


def test_existing_concept_tags_skip_link_tool():
    backend = FakeBackend(tags=[], candidates=[WIFI_CAND])
    result = triage_report(None, report([WIFI_TAG]), backend=backend, classifier=None,
                           governor=governor())
    assert [e.tool for e in result.governance] == [SEARCH_BUCKETS]
    assert result.disposition == "existing_bucket"


# --- governance: fail closed ---------------------------------------------------------------


class RaisingEvaluator:
    def evaluate(self, tool_name, args, caller):
        raise ConnectionError("policy service down")


ORGANIZER = CallerContext(user_id="u", role=ROLE_ORGANIZER)
ASSIGN_ARGS = {"report_id": "r1", "bucket_id": "bWifi"}


@pytest.mark.parametrize("evaluator, rule", [
    (RaisingEvaluator(), "evaluator-error"),
    (None, "evaluator-unavailable"),
])
def test_evaluator_unavailable_or_raising_denies_without_mutation(evaluator, rule):
    backend = FakeBackend(candidates=[WIFI_CAND])
    call = Governor(evaluator=evaluator).call(
        build_registry(backend, None), ASSIGN_REPORT, ASSIGN_ARGS, ORGANIZER
    )
    assert not call.allowed
    assert call.event.decision == "deny" and call.event.rule == rule
    assert backend.mutations == []


@pytest.mark.parametrize("args", [
    {"report_id": "r1"},  # no target
    {"report_id": "r1", "bucket_id": "bWifi", "new_bucket_title": "x"},  # two targets
    {"report_id": "r1", "bucket_id": 7},  # wrong type
    {"report_id": "r1", "bucket_id": "bWifi", "extra": "x"},  # unknown key
    {"report_id": "r1; drop", "bucket_id": "bWifi"},  # bad id
])
def test_malformed_args_deny_without_mutation(args):
    backend = FakeBackend(candidates=[WIFI_CAND])
    call = governor().call(build_registry(backend, None), ASSIGN_REPORT, args, ORGANIZER)
    assert not call.allowed and call.event.rule == "args-invalid"
    assert backend.mutations == []


@pytest.mark.parametrize("caller, rule", [
    (CallerContext(user_id="a", role=ROLE_TRIAGE_AGENT), "role-not-allowed"),
    (CallerContext(user_id="", role=ROLE_ORGANIZER), "identity-missing"),
    (CallerContext(user_id="a", role=""), "identity-missing"),
    (CallerContext(user_id="a", role="admin"), "role-not-allowed"),
])
def test_assign_requires_organizer_identity(caller, rule):
    backend = FakeBackend(candidates=[WIFI_CAND])
    call = governor().call(build_registry(backend, None), ASSIGN_REPORT, ASSIGN_ARGS, caller)
    assert not call.allowed and call.event.rule == rule
    assert backend.mutations == []


def test_unknown_tool_denied():
    call = governor().call(build_registry(FakeBackend(), None), "friction.drop_index", {},
                           ORGANIZER)
    assert not call.allowed and call.event.rule == "tool-unknown"


def test_audit_never_stores_report_text():
    gov = governor()
    triage_report(None, report(), backend=FakeBackend(tags=[FOOD_TAG], candidates=[WIFI_CAND]),
                  classifier=None, governor=gov)
    records = gov.audit_records()
    assert records
    assert WIFI_TEXT not in repr([r.args for r in records])
    link = next(r for r in records if r.tool_name == LINK_CONCEPTS)
    assert link.args == {"text": {"len": len(WIFI_TEXT)}}


# --- manifest ------------------------------------------------------------------------------


def test_manifest_export_is_deterministic_and_committed():
    first = export_tool_manifest()
    assert first == export_tool_manifest()
    committed = Path(__file__).resolve().parents[1] / "kei" / "tool-manifest.json"
    assert committed.read_text(encoding="utf-8") == first
    assert '"friction.assign_report"' in first and '"operation_class": "write"' in first


# --- HTTP ----------------------------------------------------------------------------------


@pytest.fixture
def api():
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND, FOOD_CAND])
    gov = governor()
    app = FastAPI()
    app.include_router(triage_router.router)
    app.state.elasticsearch = object()
    app.dependency_overrides[triage_router.get_backend] = lambda: backend
    app.dependency_overrides[triage_router.get_governor] = lambda: gov
    app.dependency_overrides[triage_router.get_classifier] = lambda: None
    return TestClient(app), backend


def test_triage_endpoint_proposes_and_does_not_assign(api):
    client, backend = api
    resp = client.post("/api/reports/r1/triage")
    assert resp.status_code == 200
    assert resp.json()["disposition"] == "existing_bucket"
    assert backend.reports["r1"].status == "proposed"
    assert backend.reports["r1"].bucket_id is None
    assert backend.mutations == []
    assert client.post("/api/reports/missing/triage").status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-Role": "triage-agent"}, {"X-Role": "attendee"}])
def test_confirm_without_organizer_role_is_403_and_unchanged(api, headers):
    client, backend = api
    before = backend.reports["r1"]
    resp = client.post("/api/reports/r1/confirm", json={"bucket_id": "bWifi"}, headers=headers)
    assert resp.status_code == 403
    event = resp.json()["detail"]["governance"]
    assert event["decision"] == "deny" and event["tool"] == ASSIGN_REPORT
    assert backend.mutations == []
    assert backend.reports["r1"] == before


def test_confirm_as_organizer_assigns(api):
    client, backend = api
    resp = client.post("/api/reports/r1/confirm", json={"bucket_id": "bWifi"},
                       headers={"X-Role": "organizer"})
    assert resp.status_code == 200
    assert resp.json()["bucket_id"] == "bWifi"
    assert backend.mutations == [("assign_report", "r1", "bWifi")]
    audit = client.get("/api/audit?limit=5").json()
    assert audit[0]["tool"] == ASSIGN_REPORT and audit[0]["decision"] == "allow"


def test_confirm_new_bucket_creates_then_assigns(api):
    client, backend = api
    resp = client.post("/api/reports/r1/confirm",
                       json={"new_bucket_title": "Hall B wifi", "new_bucket_summary": "s"},
                       headers={"X-Role": "organizer"})
    assert resp.status_code == 200
    assert [m[0] for m in backend.mutations] == ["create_bucket", "assign_report"]


def test_confirm_rejects_ambiguous_body(api):
    client, backend = api
    resp = client.post("/api/reports/r1/confirm", json={}, headers={"X-Role": "organizer"})
    assert resp.status_code == 422
    assert backend.mutations == []


def test_concepts_endpoint(api):
    client, _ = api
    assert client.get("/api/concepts?q=wifi").json()[0]["concept_id"] == "fd:WifiOutage"


def test_confirm_unknown_report_is_404(api):
    client, backend = api
    resp = client.post("/api/reports/nope/confirm", json={"bucket_id": "bWifi"},
                       headers={"X-Role": "organizer"})
    assert resp.status_code == 404


def test_main_app_mounts_triage_routes():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert {"/api/reports/{report_id}/triage", "/api/reports/{report_id}/confirm",
            "/api/audit", "/api/concepts"} <= paths


# --- Elastic inference provider ----------------------------------------------------------


class FakeInference:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"completion": [{"result": self.answer}]}


class FakeES:
    def __init__(self, inference):
        self.inference = inference


ELASTIC_MATCH = ('```json\n{"bucket_id":"bWifi","new_bucket_title":null,'
                 '"new_bucket_summary":null,"confidence":0.9,"rationale":"Same wifi issue."}\n```')


def test_elastic_classifier_parses_fenced_json():
    inference = FakeInference(answer=ELASTIC_MATCH)
    clf = ElasticInferenceClassifier(FakeES(inference), inference_id=".x-completion")
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND, FOOD_CAND])
    result = triage_report(None, report(), backend=backend, classifier=clf, governor=governor())
    assert result.disposition == "existing_bucket" and result.bucket_id == "bWifi"
    assert result.rationale == "Same wifi issue."
    assert result.extractor_version == "triage-v1:elastic:.x-completion"
    call = inference.calls[0]
    assert call["inference_id"] == ".x-completion" and call["timeout"] == "15s"
    assert "Respond with ONLY one JSON object" in call["input"] and WIFI_TEXT in call["input"]


@pytest.mark.parametrize("fake", [
    FakeInference(answer="I think it is the wifi bucket."),  # no JSON
    FakeInference(answer='{"bucket_id":"invented","confidence":0.9,"rationale":"x"}'),
    FakeInference(answer='{"bucket_id":null,"confidence":2,"rationale":"x"}'),  # invalid
    FakeInference(error=ConnectionError("inference down")),
])
def test_elastic_classifier_bad_answers_fall_back(fake):
    clf = ElasticInferenceClassifier(FakeES(fake), inference_id=".x-completion")
    backend = FakeBackend(tags=[WIFI_TAG], candidates=[WIFI_CAND])
    result = triage_report(None, report(), backend=backend, classifier=clf, governor=governor())
    assert result.extractor_version == "triage-v1:elastic:.x-completion|fallback-v1"
    assert result.bucket_id == "bWifi"


def test_provider_selection(monkeypatch):
    es = FakeES(FakeInference(answer="{}"))
    monkeypatch.delenv("FD_TRIAGE_PROVIDER", raising=False)
    monkeypatch.delenv("FD_TRIAGE_INFERENCE_ID", raising=False)
    default = default_classifier(es)
    assert isinstance(default, ElasticInferenceClassifier)
    assert default.version == "triage-v1:elastic:.anthropic-claude-5-sonnet-completion"
    assert default_classifier(None) is None
    monkeypatch.setenv("FD_TRIAGE_INFERENCE_ID", ".zai-glm-5.3-completion")
    assert default_classifier(es).inference_id == ".zai-glm-5.3-completion"
    monkeypatch.setenv("FD_TRIAGE_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert default_classifier(es) is None
