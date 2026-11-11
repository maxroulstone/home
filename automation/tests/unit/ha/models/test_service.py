"""Validate outgoing HA service-call models."""

import pytest
from pydantic import ValidationError

from automation.ha.models import ServiceCall


@pytest.mark.parametrize(
    "field, value",
    [("domain", True), ("entity_ids", "light.lounge"), ("typo", "unexpected")],
)
def test_service_call_rejects_invalid_fields(field, value):
    with pytest.raises(ValidationError):
        ServiceCall.model_validate(
            {
                "domain": "light",
                "service": "turn_on",
                "entity_ids": ("light.lounge",),
                field: value,
            }
        )
