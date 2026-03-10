from __future__ import annotations

import asyncio

from openai_codex_oauth_example import main


def test_cli_routes_to_login(monkeypatch):
    called = {"login": False, "run": False}

    async def fake_run_login(auth_file, originator, no_browser):
        called["login"] = True
        assert auth_file == "/tmp/auth.json"
        assert originator == "pi"
        assert no_browser is True

    async def fake_run(prompt):
        called["run"] = True

    monkeypatch.setattr(main, "run_login", fake_run_login)
    monkeypatch.setattr(main, "run", fake_run)
    monkeypatch.setattr(main, "asyncio", asyncio)
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--login", "--auth-file", "/tmp/auth.json", "--no-browser"],
    )

    main.cli()
    assert called["login"] is True
    assert called["run"] is False


def test_cli_routes_to_prompt_run(monkeypatch):
    called = {"login": False, "run": False}

    async def fake_run_login(auth_file, originator, no_browser):
        called["login"] = True

    async def fake_run(prompt):
        called["run"] = True
        assert prompt == "hello"

    monkeypatch.setattr(main, "run_login", fake_run_login)
    monkeypatch.setattr(main, "run", fake_run)
    monkeypatch.setattr(main, "asyncio", asyncio)
    monkeypatch.setattr("sys.argv", ["prog", "--prompt", "hello"])

    main.cli()
    assert called["run"] is True
    assert called["login"] is False
