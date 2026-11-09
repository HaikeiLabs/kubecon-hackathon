import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from elastic_transport import TransportError
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ApiError
from fastapi import FastAPI, HTTPException, Query, Request, status

from app.models import Bucket, BucketSearchResult, Report, ReportSubmission

REPORTS_INDEX = "friction-desk-reports-v1"
BUCKETS_INDEX = "friction-desk-buckets-v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Elasticsearch(
        os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
        api_key=os.getenv("ELASTICSEARCH_API_KEY") or None,
    )
    app.state.elasticsearch = client
    try:
        ensure_indices(client)
        yield
    finally:
        client.close()


def ensure_indices(client: Elasticsearch) -> None:
    indexes = {
        REPORTS_INDEX: {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "description": {"type": "text"},
                    "location": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "created_at": {"type": "date"},
                    "status": {"type": "keyword"},
                    "bucket_id": {"type": "keyword"},
                }
            }
        },
        BUCKETS_INDEX: {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "summary": {"type": "text"},
                    "status": {"type": "keyword"},
                    "report_count": {"type": "integer"},
                    "updated_at": {"type": "date"},
                }
            }
        },
    }
    for name, body in indexes.items():
        if not client.indices.exists(index=name):
            client.indices.create(index=name, **body)


def get_client(request: Request) -> Elasticsearch:
    return request.app.state.elasticsearch


app = FastAPI(
    title="Conference Friction Desk API",
    version="0.1.0",
    description="Anonymous attendee reports and organizer search API.",
    lifespan=lifespan,
)


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
    """Persist an anonymous report; triage assignment is intentionally a later step."""
    report = Report(
        id=str(uuid4()),
        description=submission.description.strip(),
        location=submission.location.strip() if submission.location else None,
        created_at=datetime.now(UTC),
    )
    try:
        get_client(request).index(
            index=REPORTS_INDEX,
            id=report.id,
            document=report.model_dump(mode="json"),
        )
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not save report") from exc
    return report


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
    """Retrieve candidate buckets with lexical relevance; agent triage comes later."""
    try:
        result = get_client(request).search(
            index=BUCKETS_INDEX,
            size=limit,
            query={
                "bool": {
                    "must": [
                        {"term": {"status": "open"}},
                        {"multi_match": {"query": q, "fields": ["title^2", "summary"]}},
                    ]
                }
            },
        )
    except (ApiError, TransportError) as exc:
        raise HTTPException(status_code=503, detail="could not search issue buckets") from exc
    return [
        BucketSearchResult(bucket=Bucket.model_validate(hit["_source"]), score=hit["_score"])
        for hit in result["hits"]["hits"]
    ]
