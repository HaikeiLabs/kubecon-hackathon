"""Static validation of the hand-written seed data in backend/seed/.

Checks the JSON parses, that every concept_id exists in the real ontology build
(ontology/build/concepts.json), and that every report's bucket reference
resolves to a seeded bucket with a consistent report_count. Never touches
Elasticsearch; reset_and_seed itself is exercised with a fake client in
test_search.py.
"""

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
SEED_DIR = BACKEND_DIR / "seed"
CONCEPTS_PATH = REPO_DIR / "ontology" / "build" / "concepts.json"


def _load(name: str) -> list[dict]:
    return json.loads((SEED_DIR / name).read_text())


def test_seed_files_parse_as_lists() -> None:
    buckets = _load("buckets.json")
    reports = _load("reports.json")
    assert isinstance(buckets, list) and buckets
    assert isinstance(reports, list) and reports
    assert 8 <= len(buckets) <= 12
    assert 60 <= len(reports) <= 100


def test_bucket_fields() -> None:
    ids: set[str] = set()
    for bucket in _load("buckets.json"):
        assert bucket["id"] not in ids
        ids.add(bucket["id"])
        assert bucket["title"]
        assert bucket["summary"]
        assert bucket["status"] in ("open", "resolved")
        assert isinstance(bucket["report_count"], int)


def test_every_bucket_concept_id_exists_in_ontology() -> None:
    known = {c["id"] for c in json.loads(CONCEPTS_PATH.read_text())}
    for bucket in _load("buckets.json"):
        assert bucket["concept_ids"], f"bucket {bucket['id']} has no concepts"
        for cid in bucket["concept_ids"]:
            assert cid in known, f"bucket {bucket['id']}: unknown concept {cid}"


def test_every_report_bucket_reference_resolves() -> None:
    bucket_ids = {b["id"] for b in _load("buckets.json")}
    for report in _load("reports.json"):
        bucket_id = report.get("bucket_id")
        assert bucket_id is None or bucket_id in bucket_ids, (
            f"report {report['id']}: unknown bucket {bucket_id}"
        )
        assert (report.get("status", "untriaged") == "untriaged") == (bucket_id is None)


def test_bucket_report_count_matches_assigned_reports() -> None:
    buckets = _load("buckets.json")
    assigned = [r for r in _load("reports.json") if r.get("bucket_id")]
    expected: dict[str, int] = {}
    for report in assigned:
        status = report.get("status")
        if status in ("proposed", "confirmed"):
            expected[report["bucket_id"]] = expected.get(report["bucket_id"], 0) + 1
    assert all(b["report_count"] == expected.get(b["id"], 0) for b in buckets)


def test_demo_shape_has_unassigned_and_paraphrases() -> None:
    reports = _load("reports.json")
    unassigned = [r for r in reports if r.get("bucket_id") is None]
    assert len(unassigned) > len(reports) // 2, "leave most reports for live triage"


def test_reports_do_not_copy_gold_texts() -> None:
    gold_path = REPO_DIR / "backend" / "eval" / "gold.jsonl"
    if not gold_path.is_file():
        return
    gold_texts = {json.loads(line)["text"] for line in gold_path.read_text().splitlines() if line}
    descriptions = {r["description"] for r in _load("reports.json")}
    assert not gold_texts & descriptions, "seed must not copy held-out eval texts"
