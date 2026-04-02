"""Tests for the mock LLM provider."""

import json
import pytest

from python_template.mock_provider import (
    _detect_agent,
    _make_mock_response,
    install_mock,
    MOCK_RESPONSES,
)


class TestDetectAgent:
    def test_classifier(self):
        msgs = [{"role": "system", "content": "You are a document classifier."}]
        assert _detect_agent(msgs) == "classifier"

    def test_summarizer(self):
        msgs = [{"role": "system", "content": "You are a summarizer."}]
        assert _detect_agent(msgs) == "summarizer"

    def test_entity_extractor(self):
        msgs = [{"role": "system", "content": "You are an entity extractor."}]
        assert _detect_agent(msgs) == "entity extractor"

    def test_report_writer(self):
        msgs = [{"role": "system", "content": "You are a report writer."}]
        assert _detect_agent(msgs) == "report writer"

    def test_fallback(self):
        msgs = [{"role": "system", "content": "You are something unknown."}]
        assert _detect_agent(msgs) == "classifier"


class TestMakeResponse:
    def test_returns_valid_response(self):
        msgs = [{"role": "system", "content": "You are a document classifier."}]
        resp = _make_mock_response(msgs)
        assert len(resp.choices) == 1
        content = json.loads(resp.choices[0].message.content)
        assert content["category"] == "technical"
        assert content["confidence"] == 0.92

    def test_all_agent_types(self):
        for key, expected in MOCK_RESPONSES.items():
            msgs = [{"role": "system", "content": f"You are a {key}."}]
            resp = _make_mock_response(msgs)
            content = json.loads(resp.choices[0].message.content)
            assert content == expected

    def test_usage_fields(self):
        msgs = [{"role": "system", "content": "classifier"}]
        resp = _make_mock_response(msgs)
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 10


class TestInstallMock:
    def test_patches_litellm(self):
        import litellm
        original = litellm.acompletion
        install_mock()
        assert litellm.acompletion is not original
        # Restore
        litellm.acompletion = original
