#!/usr/bin/env python3
"""Live GitHub Copilot OAuth integration smoke test.

Run:
  cd sdk/python
  python -m pytest tests/integration/copilot/test_copilot_oauth_live.py -v --live -s
"""

from __future__ import annotations

import os
import warnings

import pytest
from flatagents import FlatAgent, ValidationWarning


@pytest.mark.asyncio
@pytest.mark.live
async def test_copilot_oauth_live_smoke() -> None:
    auth_file = os.path.expanduser(
        os.environ.get("FLATAGENTS_COPILOT_AUTH_FILE", "~/.agents/flatmachines/auth.json")
    )
    if not os.path.exists(auth_file):
        pytest.skip(f"Copilot auth file not found: {auth_file}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ValidationWarning)
        agent = FlatAgent(
            config_dict={
                "spec": "flatagent",
                "spec_version": "2.5.0",
                "data": {
                    "name": "copilot-live-smoke",
                    "model": {
                        "provider": "github-copilot",
                        "name": "gpt-4o",
                        "backend": "copilot",
                        "oauth": {
                            "provider": "github-copilot",
                            "auth_file": auth_file,
                            "refresh": True,
                        },
                    },
                    "system": "You are a concise assistant.",
                    "user": "{{ input.prompt }}",
                },
            }
        )

    result = await agent.call(prompt="Reply with exactly: COPILOT_OK")
    assert result.error is None, f"Live copilot error: {result.error}"
    assert result.content
