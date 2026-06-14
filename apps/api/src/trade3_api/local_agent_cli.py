import argparse
import asyncio
from pathlib import Path

from .local_agent_models import LocalAgentConfig
from .local_agent_worker import LocalAgentWorker


def main() -> None:
    arguments = _arguments()
    asyncio.run(_run(arguments))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Ollama task queue.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("local_agents/config.json"),
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    root = Path.cwd()
    config_path = arguments.config if arguments.config.is_absolute() else root / arguments.config
    config = LocalAgentConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    await LocalAgentWorker(config, root).run(once=arguments.once)


if __name__ == "__main__":
    main()
