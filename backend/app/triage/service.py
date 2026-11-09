"""Triage a report: governed retrieval, classification, confidence policy. Never assigns."""

from __future__ import annotations

import logging
from typing import Any

from haikeilabs.agentware.middleware.types import CallerContext
from pydantic import TypeAdapter

from app.models import BucketSearchResult, ConceptTag, GovernanceEvent, Report, TriageResult
from app.triage.llm import (
    FALLBACK_VERSION,
    Classification,
    Classifier,
    concept_overlap,
    default_classifier,
    fallback_classify,
)
from app.triage.policy import ROLE_TRIAGE_AGENT
from app.triage.tools import (
    LINK_CONCEPTS,
    PROPOSE_BUCKET,
    SEARCH_BUCKETS,
    FrictionBackend,
    Governor,
    build_registry,
    default_governor,
)

log = logging.getLogger(__name__)

EXISTING_BUCKET_MIN_CONFIDENCE = 0.75
CANDIDATE_K = 5

_tags = TypeAdapter(list[ConceptTag])
_candidates = TypeAdapter(list[BucketSearchResult])

_governor: Governor | None = None


def get_governor() -> Governor:
    """Process-wide governor so /api/audit sees every evaluation."""
    global _governor
    if _governor is None:
        _governor = default_governor()
    return _governor


def triage_agent_caller(report_id: str) -> CallerContext:
    return CallerContext(
        user_id=ROLE_TRIAGE_AGENT,
        role=ROLE_TRIAGE_AGENT,
        session_id=report_id,
        source="friction-desk-triage",
        invoking_subject=f"report:{report_id}",
    )


def decide(
    proposal: Classification,
    candidates: list[BucketSearchResult],
    concept_ids: list[str],
) -> tuple[str, Classification]:
    """Confidence policy: confident match → existing; clearly distinct → new; else review."""
    known = {c.bucket.id for c in candidates}
    if proposal.bucket_id in known and proposal.confidence >= EXISTING_BUCKET_MIN_CONFIDENCE:
        return "existing_bucket", proposal
    max_overlap = max((concept_overlap(concept_ids, c) for c in candidates), default=0.0)
    distinct = not candidates or (bool(concept_ids) and max_overlap == 0.0)
    if distinct and proposal.bucket_id is None and proposal.new_bucket_title:
        return "new_bucket", proposal
    return "needs_review", proposal


def triage_report(
    client: Any,
    report: Report,
    *,
    backend: FrictionBackend | None = None,
    classifier: Classifier | None | bool = True,
    governor: Governor | None = None,
) -> TriageResult:
    """Classify ``report`` against existing buckets. Read/propose only; never assigns.

    ``classifier=True`` picks the default (FD_TRIAGE_PROVIDER, Elastic inference unless
    set to openai), ``None``/``False``
    forces the deterministic fallback.
    """
    if backend is None:
        from app import search as backend  # type: ignore[no-redef]
    if classifier is True:
        classifier = default_classifier(client)
    governor = governor or get_governor()
    registry = build_registry(backend, client)
    caller = triage_agent_caller(report.id)
    events: list[GovernanceEvent] = []
    notes: list[str] = []

    def governed(tool: str, args: dict[str, Any]) -> Any:
        try:
            call = governor.call(registry, tool, args, caller)
        except Exception as exc:  # noqa: BLE001 - allowed call whose backend failed
            log.warning("triage tool %s failed: %s", tool, type(exc).__name__)
            notes.append(f"{tool} failed")
            return None
        events.append(call.event)
        if not call.allowed:
            notes.append(f"{tool} denied ({call.event.rule})")
        return call.data

    concepts = list(report.concept_tags)
    if not concepts:
        linked = governed(LINK_CONCEPTS, {"text": report.description})
        concepts = _tags.validate_python(linked or [], from_attributes=True)
    concept_ids = [c.concept_id for c in concepts]

    found = governed(
        SEARCH_BUCKETS,
        {"text": report.description, "concept_ids": concept_ids, "k": CANDIDATE_K},
    )
    candidates = _candidates.validate_python(found or [], from_attributes=True)

    version = FALLBACK_VERSION
    proposal: Classification | None = None
    if classifier:
        try:
            proposal = classifier.classify(report.description, concepts, candidates)
            version = classifier.version
        except Exception as exc:  # noqa: BLE001 - any LLM failure → fallback
            log.warning("triage LLM failed, using fallback: %s", type(exc).__name__)
            version = f"{classifier.version}|{FALLBACK_VERSION}"
    if proposal is None:
        proposal = fallback_classify(report.description, concepts, candidates)

    disposition, proposal = decide(proposal, candidates, concept_ids)

    if disposition == "new_bucket":
        recorded = governed(
            PROPOSE_BUCKET,
            {
                "report_id": report.id,
                "title": proposal.new_bucket_title or "",
                "summary": proposal.new_bucket_summary or "",
                "concept_ids": concept_ids,
            },
        )
        if recorded is None:
            disposition = "needs_review"

    rationale = proposal.rationale
    if notes:
        rationale = f"{rationale} [{'; '.join(notes)}]"
    return TriageResult(
        disposition=disposition,
        bucket_id=proposal.bucket_id if disposition != "new_bucket" else None,
        proposed_title=proposal.new_bucket_title if disposition != "existing_bucket" else None,
        proposed_summary=proposal.new_bucket_summary if disposition != "existing_bucket" else None,
        confidence=proposal.confidence,
        rationale=rationale,
        concept_ids=concept_ids,
        candidates=candidates,
        governance=events,
        extractor_version=version,
    )
