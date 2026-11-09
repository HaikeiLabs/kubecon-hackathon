import pytest
from pydantic import ValidationError

from app.models import ReportSubmission


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
