from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class LocalTaskMode(StrEnum):
    ANALYZE = "analyze"
    PLAN = "plan"
    REVIEW_DIFF = "review_diff"


class LocalAgentDirectories(BaseModel):
    inbox: Path
    running: Path
    done: Path
    failed: Path
    reports: Path


class LocalAgentConfig(BaseModel):
    model: str = "qwen3.5:4b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    poll_seconds: float = Field(default=5, ge=1, le=300)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    max_context_chars: int = Field(default=60_000, ge=1_000, le=250_000)
    num_context_tokens: int = Field(default=8_192, ge=2_048, le=32_768)
    num_predict_tokens: int = Field(default=1_600, ge=256, le=8_192)
    ruflo_memory_enabled: bool = True
    directories: LocalAgentDirectories


class LocalAgentTask(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{5,80}$")
    objective: str = Field(min_length=5, max_length=4_000)
    mode: LocalTaskMode = LocalTaskMode.ANALYZE
    context_files: list[str] = Field(default_factory=list, max_length=30)
    acceptance: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime


class PlannerResult(BaseModel):
    summary: str = Field(max_length=1_500)
    observations: list[str] = Field(default_factory=list, max_length=15)
    recommended_actions: list[str] = Field(default_factory=list, max_length=15)
    files_to_change: list[str] = Field(default_factory=list, max_length=20)
    tests_to_run: list[str] = Field(default_factory=list, max_length=15)
    risks: list[str] = Field(default_factory=list, max_length=15)
    blocking_questions: list[str] = Field(default_factory=list, max_length=10)
    requires_cloud_expert: bool = False


class CriticResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list, max_length=15)
    final_actions: list[str] = Field(default_factory=list, max_length=15)
    escalate_to_codex: bool = False
    escalation_reason: str = Field(default="", max_length=1_000)


class LocalAgentReport(BaseModel):
    task: LocalAgentTask
    model: str
    completed_at: datetime
    context_files_loaded: list[str]
    context_truncated: bool
    planner: PlannerResult
    critic: CriticResult
