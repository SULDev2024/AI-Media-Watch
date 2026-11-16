"""Missing reference labels must never trigger self-scoring against predictions."""
import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_missing_labels_do_not_query_prediction_database(monkeypatch):
    from aimw.api.v1.routes_validation import validation_summary
    from aimw.validation import models
    monkeypatch.setattr(models, "load_cases", lambda: [])
    def forbidden_database():
        pytest.fail("Model prediction database cannot supply ground truth")
    with pytest.raises(HTTPException) as exc:
        await validation_summary("test", None, forbidden_database)
    assert exc.value.status_code == 409
    assert "Human-labeled" in exc.value.detail


def test_validation_path_is_project_relative():
    from aimw.validation.models import _CASES_PATH
    assert _CASES_PATH.is_absolute()
    assert _CASES_PATH.parts[-3:] == ("data", "validation", "cases.jsonl")
