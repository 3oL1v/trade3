import argparse
import asyncio
from pathlib import Path

from .overnight_research import OvernightResearchConfig, OvernightResearchRunner


def main() -> None:
    arguments = _arguments()
    asyncio.run(_run(arguments))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bounded local Ollama-assisted strategy research.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("research/overnight/config.json"),
    )
    parser.add_argument("--max-hours", type=float)
    parser.add_argument("--max-trials", type=int)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    project_root = Path.cwd()
    config_path = arguments.config
    if not config_path.is_absolute():
        config_path = project_root / config_path
    config = OvernightResearchConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    updates = {}
    if arguments.max_hours is not None:
        updates["max_hours"] = arguments.max_hours
    if arguments.max_trials is not None:
        updates["max_trials"] = arguments.max_trials
    if updates:
        config = config.model_copy(update=updates)
    runner = OvernightResearchRunner(config, project_root=project_root)
    await runner.run()


if __name__ == "__main__":
    main()
