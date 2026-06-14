import argparse
import asyncio
from pathlib import Path

from .fixed_verification import FixedVerificationConfig, FixedVerificationRunner


def main() -> None:
    arguments = _arguments()
    asyncio.run(_run(arguments))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify one frozen strategy configuration on untouched data.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("research/verification/config.json"),
    )
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    project_root = Path.cwd()
    config_path = arguments.config
    if not config_path.is_absolute():
        config_path = project_root / config_path
    config = FixedVerificationConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    await FixedVerificationRunner(config, project_root=project_root).run()


if __name__ == "__main__":
    main()
