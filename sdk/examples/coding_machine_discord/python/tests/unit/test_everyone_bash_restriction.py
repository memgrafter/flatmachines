from __future__ import annotations

import asyncio

from tool_use_discord.tools import CLIToolProvider


def test_everyone_agent_bash_allows_safe_date_only(tmp_path):
    provider = CLIToolProvider(str(tmp_path), bash_mode="date-only")

    allowed = asyncio.run(
        provider.execute_tool(
            "bash",
            "call-1",
            {"command": "date +%s", "timeout": 5},
        )
    )
    assert allowed.is_error is False
    assert allowed.content.strip()

    rejected = asyncio.run(
        provider.execute_tool(
            "bash",
            "call-2",
            {"command": "ls", "timeout": 5},
        )
    )
    assert rejected.is_error is True
    assert "restricted" in rejected.content.lower()
    assert "date" in rejected.content.lower()
