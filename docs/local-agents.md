# Local Ollama + Ruflo Workflow

## Goal

Use cloud assistants only for architecture, security-sensitive changes, and
final review. Routine repository analysis and planning run locally.

## Important Boundary

The generic Ruflo daemon must stay stopped. Its `audit`, `optimize`, and
`testgaps` headless workers invoke Claude Code and consume cloud limits.

The Trade3 local worker uses:

- Ruflo for role registration and best-effort local report memory;
- Ollama `qwen3.5:4b` for planner and independent critic inference;
- a filesystem queue for deterministic, inspectable task state;
- report-only operation: it never edits production code or places orders.

## Commands

Interactive visible mode:

```powershell
.\scripts\start_visible_local_ai.ps1
```

This opens three PowerShell windows:

- `OLLAMA CHAT`: direct interactive prompts to `qwen3.5:4b`;
- `TRADE3 LOCAL WORKER`: live planner/critic task progress;
- `RUFLO CONTROL`: prompt entry, queue status, report viewer, and Ruflo commands.

Close them manually or run:

```powershell
.\scripts\stop_visible_local_ai.ps1
```

Background mode:

```powershell
.\scripts\start_local_agents.ps1

.\scripts\add_local_task.ps1 `
  -Objective "Review the risk calculator for edge cases" `
  -Mode review_diff `
  -ContextFiles @(
    "apps/api/src/trade3_api/services.py",
    "apps/api/tests/test_services.py"
  )

.\scripts\status_local_agents.ps1
.\scripts\stop_local_agents.ps1
```

Reports appear in `local_agents/reports/`. For the next cloud-assisted session,
provide only the latest report path and a short command such as:

```text
Прочитай последний local_agents report, проверь вывод и реализуй только
одобренные изменения. Ответ кратко.
```

## Task Modes

- `analyze`: understand a subsystem and list findings.
- `plan`: produce a bounded implementation plan.
- `review_diff`: include the current Git status/diff and review it.

## Escalation

The critic marks `escalate_to_codex=true` for ambiguous architecture,
security-sensitive behavior, exchange execution, secrets, or changes the local
4B model cannot validate reliably. This flag is a routing decision, not an
automatic cloud request.
