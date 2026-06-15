import asyncio
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .local_agent_models import (
    CriticResult,
    LocalAgentConfig,
    LocalAgentReport,
    LocalAgentTask,
    LocalTaskMode,
    PlannerResult,
)

BLOCKED_PARTS = {
    ".env",
    ".git",
    ".venv",
    "node_modules",
    "data",
    "runtime",
    "__pycache__",
}


class LocalOllamaAgents:
    def __init__(self, config: LocalAgentConfig, client: httpx.AsyncClient | None = None) -> None:
        parsed = urlparse(config.ollama_base_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local agents require a loopback Ollama URL")
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.ollama_base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            trust_env=False,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def plan(self, task: LocalAgentTask, context: str) -> PlannerResult:
        prompt = f"""
You are a local planning agent for the Trade3 advisory-only futures terminal.
Analyze the task and supplied repository context. Do not place orders, request
exchange credentials, browse the web, edit files, or claim profitability.
Prefer small changes, deterministic calculations, tests, and existing patterns.
Mark requires_cloud_expert=true only for security-critical, architectural, or
ambiguous work that a 4B local model should not decide.

TASK:
{task.model_dump_json()}

CONTEXT:
{context}
"""
        response = await self._generate(prompt, PlannerResult.model_json_schema(), 0.2)
        return PlannerResult.model_validate_json(response)

    async def critique(
        self,
        task: LocalAgentTask,
        planner: PlannerResult,
        context: str,
    ) -> CriticResult:
        prompt = f"""
You are the independent local critic for Trade3. Check the proposed work against
the task and repository context. Reject invented APIs, unsafe execution,
unbounded refactors, missing tests, and claims not supported by the context.
Set escalate_to_codex=true when expert review is genuinely necessary.
Do not edit files or provide live trading instructions.

TASK:
{task.model_dump_json()}

PLANNER:
{planner.model_dump_json()}

CONTEXT:
{context}
"""
        response = await self._generate(prompt, CriticResult.model_json_schema(), 0.1)
        return CriticResult.model_validate_json(response)

    async def _generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        temperature: float,
    ) -> str:
        response = await self._client.post(
            "/api/generate",
            json={
                "model": self._config.model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {
                    "temperature": temperature,
                    "num_ctx": self._config.num_context_tokens,
                    "num_predict": self._config.num_predict_tokens,
                },
            },
        )
        response.raise_for_status()
        content = response.json().get("response", "")
        if not content:
            raise ValueError("Ollama returned an empty response")
        return content


class LocalAgentWorker:
    def __init__(self, config: LocalAgentConfig, project_root: Path) -> None:
        self._config = config
        self._root = project_root.resolve()

    async def run(self, *, once: bool = False) -> None:
        directories = self._directories()
        for directory in directories.values():
            directory.mkdir(parents=True, exist_ok=True)
        print(
            f"[worker] model={self._config.model} inbox={directories['inbox']}",
            flush=True,
        )
        print("[worker] waiting for local tasks; Ctrl+C stops the worker", flush=True)
        agents = LocalOllamaAgents(self._config)
        try:
            while True:
                task_path = next(iter(sorted(directories["inbox"].glob("*.json"))), None)
                if task_path is None:
                    if once:
                        return
                    await asyncio.sleep(self._config.poll_seconds)
                    continue
                await self._process(task_path, directories, agents)
                if once:
                    return
        finally:
            await agents.close()

    async def _process(
        self,
        task_path: Path,
        directories: dict[str, Path],
        agents: LocalOllamaAgents,
    ) -> None:
        running_path = directories["running"] / task_path.name
        shutil.move(task_path, running_path)
        try:
            task = LocalAgentTask.model_validate_json(running_path.read_text(encoding="utf-8-sig"))
            print(f"\n[task] claimed {task.id}: {task.objective}", flush=True)
            context, loaded, truncated = self._context(task)
            print(
                f"[context] files={len(loaded)} chars={len(context)} truncated={truncated}",
                flush=True,
            )
            print("[planner] Ollama inference started", flush=True)
            planner = await agents.plan(task, context)
            print("[planner] completed; critic started", flush=True)
            critic = await agents.critique(task, planner, context)
            print(
                f"[critic] approved={critic.approved} escalate_to_codex={critic.escalate_to_codex}",
                flush=True,
            )
            report = LocalAgentReport(
                task=task,
                model=self._config.model,
                completed_at=datetime.now(UTC),
                context_files_loaded=loaded,
                context_truncated=truncated,
                planner=planner,
                critic=critic,
            )
            report_json = directories["reports"] / f"{task.id}.json"
            report_json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            report_md = directories["reports"] / f"{task.id}.md"
            report_md.write_text(_markdown(report), encoding="utf-8")
            shutil.move(running_path, directories["done"] / running_path.name)
            print(f"[done] report={report_md}", flush=True)
            if self._config.ruflo_memory_enabled:
                _store_ruflo_memory(self._root, report_md)
                print("[ruflo] report memory update attempted", flush=True)
        except Exception as exc:
            error_path = directories["failed"] / running_path.name
            payload = {"error": f"{type(exc).__name__}: {exc}", "failed_at": _now()}
            error_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            running_path.unlink(missing_ok=True)
            print(f"[failed] {task_path.name}: {payload['error']}", flush=True)

    def _context(self, task: LocalAgentTask) -> tuple[str, list[str], bool]:
        chunks = [f"Mode: {task.mode.value}"]
        loaded: list[str] = []
        if task.mode == LocalTaskMode.REVIEW_DIFF:
            chunks.append(_git_context(self._root))
        for relative in task.context_files:
            path = self._safe_path(relative)
            if path is None or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            chunks.append(f"\n--- FILE: {relative} ---\n{text}")
            loaded.append(relative)
        context = "\n".join(chunks)
        truncated = len(context) > self._config.max_context_chars
        return context[: self._config.max_context_chars], loaded, truncated

    def _safe_path(self, relative: str) -> Path | None:
        candidate = (self._root / relative).resolve()
        try:
            project_relative = candidate.relative_to(self._root)
        except ValueError:
            return None
        if any(
            part.lower() in BLOCKED_PARTS or "secret" in part.lower()
            for part in project_relative.parts
        ):
            return None
        return candidate

    def _directories(self) -> dict[str, Path]:
        return {
            name: (self._root / path).resolve()
            for name, path in self._config.directories.model_dump().items()
        }


def _git_context(root: Path) -> str:
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    ).stdout
    diff = subprocess.run(
        ["git", "diff", "--", "apps", "docs", "scripts"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    ).stdout
    return f"GIT STATUS:\n{status}\nGIT DIFF:\n{diff}"


def _store_ruflo_memory(root: Path, report_path: Path) -> None:
    json_path = report_path.with_suffix(".json")
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        content = json.dumps(
            {
                "report": str(report_path.resolve()),
                "task": payload.get("task", {}).get("objective", ""),
                "summary": payload.get("planner", {}).get("summary", ""),
                "escalate_to_codex": payload.get("critic", {}).get(
                    "escalate_to_codex",
                    False,
                ),
            },
            ensure_ascii=True,
        )[:8_000]
    else:
        content = json.dumps({"report": str(report_path.resolve())})
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx is None:
        return
    try:
        subprocess.run(
            [
                npx,
                "ruflo",
                "memory",
                "store",
                "-k",
                f"trade3/local/{report_path.stem}",
                "--value",
                content,
                "-n",
                "trade3-local",
                "--upsert",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _markdown(report: LocalAgentReport) -> str:
    def lines(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- none"

    return f"""# Local Agent Report: {report.task.id}

## Objective
{report.task.objective}

## Summary
{report.planner.summary}

## Observations
{lines(report.planner.observations)}

## Final Actions
{lines(report.critic.final_actions or report.planner.recommended_actions)}

## Risks
{lines(report.planner.risks)}

## Critic
- approved: {str(report.critic.approved).lower()}
- escalate_to_codex: {str(report.critic.escalate_to_codex).lower()}
- reason: {report.critic.escalation_reason or "none"}

## Context
- model: {report.model}
- files: {", ".join(report.context_files_loaded) or "none"}
- truncated: {str(report.context_truncated).lower()}
- completed_at: {report.completed_at.isoformat()}
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()
