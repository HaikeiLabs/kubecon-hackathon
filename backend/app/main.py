import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from elastic_transport import TransportError
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ApiError
from fastapi import FastAPI, HTTPException, Query, Request, status

from app import search
from app.models import Bucket, BucketSearchResult, Report, ReportSubmission, TriageResult
from app.search import BUCKETS_INDEX, REPORTS_INDEX
from app.triage.router import router as triage_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Elasticsearch(
        os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
        api_key=os.getenv("ELASTICSEARCH_API_KEY") or None,
        # Seeding writes semantic_text fields, so inference can exceed the 10s default.
        request_timeout=float(os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "120")),
    )
    app.state.elasticsearch = client
    try:
        search.ensure_indices(client)
        yield
    finally:
        client.close()


def get_client(request: Request) -> Elasticsearch:
    return request.app.state.elasticsearch


app = FastAPI(
    title="Conference Friction Desk API",
    version="0.1.0",
    description="Anonymous attendee reports and organizer search API.",
    lifespan=lifespan,
)
app.include_router(triage_router)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness(request: Request) -> dict[str, str]:
    try:
        if not get_client(request).ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="search unavailable",
            )
    except (ApiError, TransportError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="search unavailable",
        ) from exc
    return {"status": "ready"}


@app.post(
    "/api/reports",
    response_model=Report,
    status_code=status.HTTP_201_CREATED,
    tags=["reports"],
)
def submit_report(submission: ReportSubmission, request: Request) -> Report:
    """Persist an anonymous report with linked concepts and, when available, a triage proposal."""
    client = get_client(request)
    report = Report(
        id=str(uuid4()),
        description=submission.description.strip(),
        location=submission.location.strip() if submission.location else None,
        created_at=datetime.now(UTC),
    )
    try:
        report = search.apply_concept_tags(report, search.link_concepts(client, report.description))
        search.index_report(client, report)
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not save report") from exc

    triage = _load_triage()
    if triage is not None:
        try:
            result = triage(client, report)
            report = report.model_copy(update={"triage": result, "status": "proposed"})
            search.index_report(client, report)
        except Exception:  # triage is advisory; the report is already saved
            logger.exception("triage failed for report %s", report.id)
    return report


def _load_triage() -> Callable[[Any, Report], TriageResult] | None:
    try:
        from app.triage.service import triage_report
    except ImportError:
        return None
    return triage_report


@app.get("/api/reports", response_model=list[Report], tags=["reports"])
def list_reports(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> list[Report]:
    try:
        result = get_client(request).search(
            index=REPORTS_INDEX,
            size=limit,
            sort=[{"created_at": {"order": "desc"}}],
            query={"match_all": {}},
        )
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not list reports") from exc
    return [Report.model_validate(hit["_source"]) for hit in result["hits"]["hits"]]


@app.get("/api/reports/{report_id}", response_model=Report, tags=["reports"])
def get_report(report_id: str, request: Request) -> Report:
    try:
        report = search.get_report(get_client(request), report_id)
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not load report") from exc
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@app.get("/api/buckets", response_model=list[Bucket], tags=["buckets"])
def list_buckets(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> list[Bucket]:
    try:
        result = get_client(request).search(
            index=BUCKETS_INDEX,
            size=limit,
            sort=[{"updated_at": {"order": "desc"}}],
            query={"match_all": {}},
        )
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not list issue buckets") from exc
    return [Bucket.model_validate(hit["_source"]) for hit in result["hits"]["hits"]]


@app.get("/api/buckets/search", response_model=list[BucketSearchResult], tags=["buckets"])
def search_buckets(
    request: Request,
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[BucketSearchResult]:
    """Hybrid (lexical + synonyms + concepts, semantic) RRF retrieval of open buckets."""
    client = get_client(request)
    try:
        concept_ids = [tag.concept_id for tag in search.link_concepts(client, q)]
        return search.search_candidate_buckets(client, q, concept_ids, k=limit)
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not search issue buckets") from exc


@app.post("/api/admin/reset", tags=["admin"])
def reset(request: Request) -> dict[str, int]:
    """Recreate the v2 indices and reseed concepts, buckets, and reports."""
    seed_dir = Path(os.getenv("FD_SEED_DIR") or search.DEFAULT_SEED_DIR)
    try:
        return search.reset_and_seed(get_client(request), seed_dir)
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not reset search data") from exc
