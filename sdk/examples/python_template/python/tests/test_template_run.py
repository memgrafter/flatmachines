"""Integration test: run the full template machine with mock backend."""

import pytest
from python_template.main import run


class TestTemplateRun:
    @pytest.mark.asyncio
    async def test_full_run_with_mock(self):
        result = await run(use_mock=True)
        assert result is not None
        # Should have first_category from the sequential classify step
        assert "first_category" in result
        # Should have results from the foreach fan-out
        assert "results" in result
