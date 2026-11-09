"""Bucket classification: OpenAI structured output, with a deterministic fallback."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.models import BucketSearchResult, ConceptTag

DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_INFERENCE_ID = ".anthropic-claude-5-sonnet-completion"
LLM_TIMEOUT_SECONDS = 15.0
FALLBACK_VERSION = "fallback-v1"


class Classification(BaseModel):
    """What a classifier proposes; the confidence policy decides the disposition."""

    bucket_id: str | None = None
    new_bucket_title: str | None = None
    new_bucket_summary: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class Classifier(Protocol):
    version: str

    def classify(
        self, text: str, concepts: list[ConceptTag], candidates: list[BucketSearchResult]
    ) -> Classification: ...


def concept_overlap(concept_ids: list[str], candidate: BucketSearchResult) -> float:
    """Share of the report's concepts covered by the bucket's concepts or ancestors."""
    if not concept_ids:
        return 0.0
    bucket = candidate.bucket
    covered = set(bucket.concept_ids) | set(bucket.concept_ancestors)
    return len(set(concept_ids) & covered) / len(set(concept_ids))


def fallback_classify(
    text: str, concepts: list[ConceptTag], candidates: list[BucketSearchResult]
) -> Classification:
    """Deterministic choice: 0.7 * concept overlap + 0.3 * relative retrieval score."""
    concept_ids = [c.concept_id for c in concepts]
    top_score = max((c.score for c in candidates), default=0.0)
    best: tuple[float, BucketSearchResult] | None = None
    for cand in candidates:
        relative = cand.score / top_score if top_score > 0 else 0.0
        value = 0.7 * concept_overlap(concept_ids, cand) + 0.3 * relative
        if best is None or value > best[0]:
            best = (value, cand)
    if best is not None and concept_overlap(concept_ids, best[1]) > 0:
        return Classification(
            bucket_id=best[1].bucket.id,
            confidence=round(min(best[0], 1.0), 3),
            rationale=(
                f"Fallback: concept overlap {concept_overlap(concept_ids, best[1]):.2f} "
                f"with bucket '{best[1].bucket.title}'."
            ),
        )
    label = concepts[0].label if concepts else "Unclassified"
    return Classification(
        new_bucket_title=f"{label} reports",
        new_bucket_summary=text.strip()[:280],
        confidence=0.5 if concepts else 0.2,
        rationale="Fallback: no candidate bucket shares concepts with this report.",
    )


SYSTEM_PROMPT = (
    "You triage anonymous conference friction reports into issue buckets. "
    "Use only the report text, the linked concepts and the candidate buckets given. "
    "Do not invent facts, locations, counts or causes. Either choose exactly one "
    "candidate bucket_id from the list, or set bucket_id to null and propose a short "
    "new_bucket_title and a one-sentence new_bucket_summary grounded in the report. "
    "confidence is your probability (0-1) that the choice is correct."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "triage_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "bucket_id",
            "new_bucket_title",
            "new_bucket_summary",
            "confidence",
            "rationale",
        ],
        "properties": {
            "bucket_id": {"type": ["string", "null"]},
            "new_bucket_title": {"type": ["string", "null"]},
            "new_bucket_summary": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
        },
    },
}


def build_payload(
    text: str, concepts: list[ConceptTag], candidates: list[BucketSearchResult]
) -> dict[str, Any]:
    return {
        "report": text,
        "linked_concepts": [{"id": c.concept_id, "label": c.label} for c in concepts],
        "candidates": [
            {
                "bucket_id": c.bucket.id,
                "title": c.bucket.title,
                "summary": c.bucket.summary,
                "concept_ids": c.bucket.concept_ids,
                "retrieval_score": round(c.score, 4),
            }
            for c in candidates
        ],
    }


def validate_choice(result: Classification, candidates: list[BucketSearchResult]) -> Classification:
    """Reject answers that point outside the candidate list or choose nothing."""
    known = {c.bucket.id for c in candidates}
    if result.bucket_id is not None and result.bucket_id not in known:
        raise ValueError("model chose a bucket that is not a candidate")
    if result.bucket_id is None and not result.new_bucket_title:
        raise ValueError("model chose neither a candidate nor a new bucket")
    return result


def parse_json_answer(raw: str) -> Classification:
    """Parse a model's JSON answer, tolerating code fences and surrounding prose."""
    body = raw.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0]
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model answer")
    return Classification.model_validate_json(body[start : end + 1])


class OpenAIClassifier:
    def __init__(self, model: str | None = None, client: Any = None) -> None:
        self.model = model or os.getenv("FD_TRIAGE_MODEL", DEFAULT_MODEL)
        self.version = f"triage-v1:{self.model}"
        if client is None:
            from openai import OpenAI

            client = OpenAI(timeout=LLM_TIMEOUT_SECONDS, max_retries=0)
        self._client = client

    def classify(
        self, text: str, concepts: list[ConceptTag], candidates: list[BucketSearchResult]
    ) -> Classification:
        payload = build_payload(text, concepts, candidates)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
            temperature=0,
            timeout=LLM_TIMEOUT_SECONDS,
        )
        result = Classification.model_validate_json(response.choices[0].message.content)
        return validate_choice(result, candidates)


JSON_INSTRUCTIONS = (
    "Respond with ONLY one JSON object, no code fences and no prose, with exactly these "
    'keys: {"bucket_id": string or null, "new_bucket_title": string or null, '
    '"new_bucket_summary": string or null, "confidence": number between 0 and 1, '
    '"rationale": string}. bucket_id must be one of the candidate bucket_id values or null.'
)


class ElasticInferenceClassifier:
    """Classify with an Elastic inference COMPLETION endpoint (no extra secret needed)."""

    def __init__(self, es_client: Any, inference_id: str | None = None) -> None:
        self.inference_id = inference_id or os.getenv(
            "FD_TRIAGE_INFERENCE_ID", DEFAULT_INFERENCE_ID
        )
        self.version = f"triage-v1:elastic:{self.inference_id}"
        self._es = es_client

    def classify(
        self, text: str, concepts: list[ConceptTag], candidates: list[BucketSearchResult]
    ) -> Classification:
        prompt = "\n\n".join(
            [
                SYSTEM_PROMPT,
                JSON_INSTRUCTIONS,
                "Input:",
                json.dumps(build_payload(text, concepts, candidates), ensure_ascii=False),
            ]
        )
        response = self._es.inference.completion(
            inference_id=self.inference_id,
            input=prompt,
            timeout=f"{int(LLM_TIMEOUT_SECONDS)}s",
        )
        body = getattr(response, "body", response)
        answer = body["completion"][0]["result"]
        return validate_choice(parse_json_answer(answer), candidates)


def default_classifier(es_client: Any = None) -> Classifier | None:
    """Pick the provider from FD_TRIAGE_PROVIDER (elastic | openai); None → fallback."""
    provider = os.getenv("FD_TRIAGE_PROVIDER", "elastic").strip().lower()
    try:
        if provider == "elastic":
            return ElasticInferenceClassifier(es_client) if es_client is not None else None
        if provider == "openai" and os.getenv("OPENAI_API_KEY"):
            return OpenAIClassifier()
    except Exception:  # noqa: BLE001 - misconfigured client → deterministic fallback
        return None
    return None
