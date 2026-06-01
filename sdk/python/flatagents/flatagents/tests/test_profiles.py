"""Tests for model profile resolution."""

import pytest

from flatagents.profiles import ProfileManager


def test_missing_override_profile_fails_fast_with_actionable_message():
    manager = ProfileManager(
        {
            "profiles": {
                "cheap": {"provider": "cerebras", "name": "zai-glm-4.6"},
            },
            "default": "cheap",
            "override": "fast",
        }
    )

    with pytest.raises(ValueError) as exc_info:
        manager.resolve_model_config(None)

    message = str(exc_info.value)
    assert "Override profile 'fast' not found" in message
    assert "intended model override was NOT applied" in message
    assert "cheap" in message
