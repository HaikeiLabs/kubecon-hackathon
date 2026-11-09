from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportSubmission(BaseModel):
    """Anonymous attendee input. Deliberately excludes identity/contact fields."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=8, max_length=4000)
    location: str | None = Field(default=None, max_length=160)


class ConceptTag(BaseModel):
    concept_id: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    method: Literal["exact", "hybrid", "llm"]


class Bucket(BaseModel):
    id: str
    title: str
    summary: str
    status: Literal["open", "resolved"] = "open"
    report_count: int = 0
    updated_at: datetime
    concept_ids: list[str] = Field(default_factory=list)
    concept_ancestors: list[str] = Field(default_factory=list)
    category: str | None = None


class BucketSearchResult(BaseModel):
    bucket: Bucket
    score: float


class GovernanceEvent(BaseModel):
    tool: str
    decision: Literal["allow", "deny"]
    rule: str
    reason: str
    at: datetime


class TriageResult(BaseModel):
    disposition: Literal["existing_bucket", "new_bucket", "needs_review"]
    bucket_id: str | None = None
    proposed_title: str | None = None
    proposed_summary: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    concept_ids: list[str] = Field(default_factory=list)
    candidates: list[BucketSearchResult] = Field(default_factory=list)
    governance: list[GovernanceEvent] = Field(default_factory=list)
    extractor_version: str


class Report(BaseModel):
    id: str
    description: str
    location: str | None = None
    created_at: datetime
    status: Literal["untriaged", "proposed", "confirmed"] = "untriaged"
    bucket_id: str | None = None
    concept_tags: list[ConceptTag] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)
    concept_ancestors: list[str] = Field(default_factory=list)
    triage: TriageResult | None = None


class ConfirmRequest(BaseModel):
    """Organizer decision: exactly one of an existing bucket or a new bucket title."""

    model_config = ConfigDict(extra="forbid")

    bucket_id: str | None = None
    new_bucket_title: str | None = Field(default=None, max_length=200)
    new_bucket_summary: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> ConfirmRequest:
        if (self.bucket_id is None) == (self.new_bucket_title is None):
            raise ValueError("provide exactly one of bucket_id or new_bucket_title")
        return self
