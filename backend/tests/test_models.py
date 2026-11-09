import pytest
from pydantic import ValidationError

from app.models import ConceptTag, ConfirmRequest, Report, ReportSubmission


def test_report_submission_accepts_anonymous_report() -> None:
    report = ReportSubmission(description="The ramp entrance is blocked", location="Hall B")

    assert report.description == "The ramp entrance is blocked"
    assert report.location == "Hall B"


def test_report_submission_rejects_identity_fields() -> None:
    with pytest.raises(ValidationError):
        ReportSubmission.model_validate(
            {"description": "The ramp entrance is blocked", "email": "attendee@example.com"}
        )


def test_report_submission_requires_a_useful_description() -> None:
    with pytest.raises(ValidationError):
        ReportSubmission(description="bad")


def test_confirm_request_requires_exactly_one_target() -> None:
    assert ConfirmRequest(bucket_id="b1").bucket_id == "b1"
    assert ConfirmRequest(new_bucket_title="Wi-Fi outage").new_bucket_title == "Wi-Fi outage"
    with pytest.raises(ValidationError):
        ConfirmRequest()
    with pytest.raises(ValidationError):
        ConfirmRequest(bucket_id="b1", new_bucket_title="x")


def test_report_defaults_include_concepts_and_no_triage() -> None:
    report = Report(id="r1", description="wifi down", created_at="2026-11-09T12:00:00Z")

    assert report.concept_tags == [] and report.concept_ids == [] and report.concept_ancestors == []
    assert report.triage is None
    with pytest.raises(ValidationError):
        ConceptTag(concept_id="fd:Wifi", label="Wi-Fi", confidence=1.5, method="exact")
