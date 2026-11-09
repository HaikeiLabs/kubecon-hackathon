"""Triage HTTP API: agent triage, organizer confirmation, audit and concept lookup."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from haikeilabs.agentware.middleware.types import CallerContext

from app.models import ConceptTag, ConfirmRequest, Report, TriageResult
from app.triage.service import get_governor, triage_report
from app.triage.tools import ASSIGN_REPORT, FrictionBackend, Governor, build_registry

router = APIRouter(tags=["triage"])


def get_backend() -> Any:
    from app import search

    return search


def get_es(request: Request) -> Any:
    return request.app.state.elasticsearch


def get_classifier() -> Any:
    return True  # service default: OpenAI when configured, else fallback


def _load_report(backend: Any, client: Any, report_id: str) -> Report:
    report = backend.get_report(client, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@router.post("/api/reports/{report_id}/triage", response_model=TriageResult)
def triage(
    report_id: str,
    client: Any = Depends(get_es),
    backend: Any = Depends(get_backend),
    classifier: Any = Depends(get_classifier),
    governor: Governor = Depends(get_governor),
) -> TriageResult:
    report = _load_report(backend, client, report_id)
    result = triage_report(
        client, report, backend=backend, classifier=classifier, governor=governor
    )
    if report.status == "untriaged":
        report = report.model_copy(update={"triage": result, "status": "proposed"})
    else:
        report = report.model_copy(update={"triage": result})
    backend.index_report(client, report)
    return result


@router.post("/api/reports/{report_id}/confirm", response_model=Report)
def confirm(
    report_id: str,
    body: ConfirmRequest,
    x_role: str | None = Header(default=None),
    client: Any = Depends(get_es),
    backend: FrictionBackend = Depends(get_backend),
    governor: Governor = Depends(get_governor),
) -> Report:
    """Organizer-only: every confirmation is authorized by the governed assign tool."""
    role = (x_role or "").strip()
    caller = CallerContext(
        user_id="organizer-console" if role else "",
        role=role,
        session_id=report_id,
        source="friction-desk-console",
        invoking_subject="organizer-console" if role else "",
    )
    args: dict[str, Any] = {"report_id": report_id}
    if body.bucket_id is not None:
        args["bucket_id"] = body.bucket_id
    else:
        args["new_bucket_title"] = body.new_bucket_title
        args["new_bucket_summary"] = body.new_bucket_summary or ""
    try:
        call = governor.call(build_registry(backend, client), ASSIGN_REPORT, args, caller)
    except Exception as exc:  # noqa: BLE001 - authorized, but the store failed
        raise HTTPException(status_code=503, detail="could not assign report") from exc
    if not call.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"governance": call.event.model_dump(mode="json")},
        )
    return call.data


@router.get("/api/audit")
def audit(
    limit: int = Query(default=50, ge=1, le=500),
    governor: Governor = Depends(get_governor),
) -> list[dict[str, Any]]:
    """Most recent governance decisions first; arguments are already sanitized."""
    return [
        {
            "tool": r.tool_name,
            "decision": r.decision.action.value,
            "rule": r.decision.rule,
            "reason": r.decision.reason,
            "at": r.timestamp.isoformat(),
            "session_id": r.session_id,
            "invoking_subject": r.invoking_subject,
            "args": r.args,
        }
        for r in governor.audit_records(limit)
    ]


@router.get("/api/concepts", response_model=list[ConceptTag])
def concepts(
    q: str = Query(min_length=2, max_length=500),
    client: Any = Depends(get_es),
    backend: Any = Depends(get_backend),
) -> list[ConceptTag]:
    return backend.link_concepts(client, q)
