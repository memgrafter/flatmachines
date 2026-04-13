from __future__ import annotations

from tool_use_discord.responder import split_discord_message


def test_split_discord_message_no_truncation():
    text = "line1\nline2\n" + ("x" * 2100)
    chunks = split_discord_message(text, max_chars=2000)

    assert len(chunks) >= 2
    assert "".join(chunks) == text
    assert all(len(chunk) <= 2000 for chunk in chunks)
