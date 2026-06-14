import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from trade3_api.local_agent_models import (
    CriticResult,
    LocalAgentConfig,
    LocalAgentTask,
    PlannerResult,
)
from trade3_api.local_agent_worker import LocalAgentWorker, LocalOllamaAgents


def config(root: Path, *, ruflo: bool = False) -> LocalAgentConfig:
    return LocalAgentConfig.model_validate(
        {
            "model": "test-model",
            "ollama_base_url": "http://127.0.0.1:11434",
            "ruflo_memory_enabled": ruflo,
            "directories": {
                "inbox": "local_agents/inbox",
                "running": "local_agents/running",
                "done": "local_agents/done",
                "failed": "local_agents/failed",
                "reports": "local_agents/reports",
            },
        }
    )


@pytest.mark.asyncio
async def test_local_ollama_agents_use_structured_planner_and_critic() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert body["think"] is False
        assert body["format"]["type"] == "object"
        if calls == 1:
            response = PlannerResult(
                summary="Small reviewed change.",
                recommended_actions=["Add one test."],
                tests_to_run=["pytest"],
            ).model_dump_json()
        else:
            response = CriticResult(
                approved=True,
                final_actions=["Add one test."],
            ).model_dump_json()
        return httpx.Response(200, json={"response": response})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:11434",
    )
    agents = LocalOllamaAgents(config(Path(".")), client=client)
    task = LocalAgentTask(
        id="task-20260613-abcdef",
        objective="Review a bounded change.",
        created_at=datetime.now(UTC),
    )

    planner = await agents.plan(task, "context")
    critic = await agents.critique(task, planner, "context")

    assert planner.tests_to_run == ["pytest"]
    assert critic.approved is True
    assert calls == 2
    await client.aclose()


def test_context_blocks_secrets_and_paths_outside_project(tmp_path: Path) -> None:
    worker = LocalAgentWorker(config(tmp_path), tmp_path)
    (tmp_path / "allowed.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    task = LocalAgentTask(
        id="task-20260613-abcdef",
        objective="Inspect supplied files.",
        context_files=["allowed.py", ".env", "../outside.txt"],
        created_at=datetime.now(UTC),
    )

    context, loaded, truncated = worker._context(task)

    assert "print('ok')" in context
    assert "SECRET=value" not in context
    assert loaded == ["allowed.py"]
    assert truncated is False


def test_powershell_utf8_bom_task_is_supported(tmp_path: Path) -> None:
    task = LocalAgentTask(
        id="task-20260613-abcdef",
        objective="Inspect supplied files.",
        created_at=datetime.now(UTC),
    )
    task_path = tmp_path / "task.json"
    task_path.write_text(task.model_dump_json(), encoding="utf-8-sig")

    loaded = LocalAgentTask.model_validate_json(task_path.read_text(encoding="utf-8-sig"))

    assert loaded.id == task.id
