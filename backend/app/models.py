from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportSubmission(BaseModel):
    """Anonymous attendee input. Deliberately excludes identity/contact fields."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=8, max_length=4000)
    location: str | None = Field(default=None, max_length=160)


class Report(BaseModel):
    id: str
    description: str
    location: str | None = None
    created_at: datetime
    status: Literal["untriaged", "proposed", "confirmed"] = "untriaged"
    bucket_id: str | None = None


class Bucket(BaseModel):
    id: str
    title: str
    summary: str
    status: Literal["open", "resolved"] = "open"
    report_count: int = 0
    updated_at: datetime


class BucketSearchResult(BaseModel):
    bucket: Bucket
    score: float
