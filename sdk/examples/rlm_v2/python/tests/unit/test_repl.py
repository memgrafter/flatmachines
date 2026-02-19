from __future__ import annotations

from rlm_v2.repl import REPLRegistry, extract_repl_blocks


def test_extract_repl_blocks_multiple() -> None:
    text = """
Before
```repl
x = 1
print(x)
```
Middle
```repl
y = x + 1
print(y)
```
After
"""
    blocks = extract_repl_blocks(text)
    assert len(blocks) == 2
    assert "x = 1" in blocks[0]
    assert "y = x + 1" in blocks[1]


def test_repl_session_persistence_across_execs() -> None:
    sid = REPLRegistry.create_session(
        context_value="hello world",
        llm_query_fn=lambda prompt, model=None: "stub",
    )

    session = REPLRegistry.get_session(sid)

    result1 = session.execute("x = 41")
    assert not result1.had_error

    result2 = session.execute("x = x + 1\nprint(x)")
    assert "42" in result2.stdout
    assert "x" in result2.changed_vars


def test_llm_query_is_available_in_repl() -> None:
    sid = REPLRegistry.create_session(
        context_value="ctx",
        llm_query_fn=lambda prompt, model=None: f"answer:{prompt}",
    )

    session = REPLRegistry.get_session(sid)
    result = session.execute("out = llm_query('Q')\nprint(out)")

    assert "answer:Q" in result.stdout
    assert not result.had_error


def test_registry_delete_session() -> None:
    sid = REPLRegistry.create_session(
        context_value="ctx",
        llm_query_fn=lambda prompt, model=None: "ok",
    )
    assert REPLRegistry.has_session(sid)
    REPLRegistry.delete_session(sid)
    assert not REPLRegistry.has_session(sid)
