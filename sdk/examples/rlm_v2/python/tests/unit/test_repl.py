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


def test_repl_allows_import_and_standard_python() -> None:
    """REPL runs unrestricted Python, matching the paper's design."""
    sid = REPLRegistry.create_session(
        context_value="ctx",
        llm_query_fn=lambda prompt, model=None: "ok",
    )

    session = REPLRegistry.get_session(sid)
    result = session.execute(
        """
import re
import json
import math
from collections import Counter, defaultdict

match = re.search(r"(abc)", "zabc")
print(match.group(1))
print(json.dumps({"k": 1}, sort_keys=True))
print(int(math.sqrt(9)))
print(Counter(["a", "a", "b"])["a"])
bag = defaultdict(int)
bag["x"] += 1
print(bag["x"])
print(dir({}))
""".strip()
    )

    assert not result.had_error
    assert "abc" in result.stdout
    assert '{"k": 1}' in result.stdout
    assert "3" in result.stdout
    assert "2" in result.stdout
    assert "1" in result.stdout


def test_registry_delete_session() -> None:
    sid = REPLRegistry.create_session(
        context_value="ctx",
        llm_query_fn=lambda prompt, model=None: "ok",
    )
    assert REPLRegistry.has_session(sid)
    REPLRegistry.delete_session(sid)
    assert not REPLRegistry.has_session(sid)
