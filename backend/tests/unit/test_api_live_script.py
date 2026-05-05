"""Contract tests for the live API validation helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LIVE_SCRIPT_PATH = PROJECT_ROOT / "tests" / "api_live_test.py"


class RecordingRunner:
    """Small TestRunner stand-in that records requested endpoints."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        name: str,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> None:
        self.calls.append(
            {
                "name": name,
                "method": method,
                "url": url,
                "kwargs": kwargs,
            }
        )


def load_live_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_live_test", LIVE_SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_suite_uses_pipeline_endpoints_only() -> None:
    module = load_live_script()
    runner = RecordingRunner()

    module.run_smoke_tests(runner)

    urls = [call["url"] for call in runner.calls]
    assert "/api/pipelines/templates" in urls
    assert "/api/pipelines/execute" in urls
    assert all(not url.startswith("/api/workflows") for url in urls)


def test_infra_suite_avoids_llm_dependent_agent_invocation() -> None:
    module = load_live_script()
    runner = RecordingRunner()

    module.run_infra_tests(runner)

    urls = [call["url"] for call in runner.calls]
    assert "/api/health" in urls
    assert "/api/config" in urls
    assert "/api/agents" in urls
    assert "/api/pipelines/templates" in urls
    assert all("/invoke" not in url for url in urls)
