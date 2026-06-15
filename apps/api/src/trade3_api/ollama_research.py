import json
from typing import Any

import httpx
from pydantic import BaseModel, Field

from .strategy_v2 import StrategyV2Parameters


class StrategyProposal(BaseModel):
    parameters: StrategyV2Parameters
    rationale: str = Field(max_length=500)


class StrategyCritique(BaseModel):
    accepted: bool
    parameters: StrategyV2Parameters
    critique: str = Field(max_length=500)


class OllamaResearchAgents:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 120,
    ) -> None:
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def propose(
        self,
        *,
        trial_number: int,
        history: list[dict[str, Any]],
    ) -> StrategyProposal:
        prompt = f"""
You are the proposer in a constrained offline futures-strategy research loop.
You may only choose numeric parameters from the supplied JSON schema.
Do not invent indicators, code, leverage, position size, or trading instructions.
Seek robust train/validation performance, enough trades, and lower drawdown.
Avoid copying an existing parameter set exactly. This is trial {trial_number}.

Recent and leading trials:
{json.dumps(history, ensure_ascii=True)}

Return one diverse parameter proposal and a short rationale.
"""
        payload = await self._generate(
            prompt, StrategyProposal.model_json_schema(), temperature=0.8
        )
        return StrategyProposal.model_validate_json(payload)

    async def critique(
        self,
        *,
        proposal: StrategyProposal,
        history: list[dict[str, Any]],
    ) -> StrategyCritique:
        prompt = f"""
You are the critic in a constrained offline futures-strategy research loop.
Review the proposed numeric parameters for overfitting, too few likely signals,
unrealistic stops, excessive costs, and lack of diversity from prior trials.
You may accept them or return a corrected parameter set within the JSON schema.
Never propose code, leverage, position sizing, order placement, or live trading.

Proposal:
{proposal.model_dump_json()}

Prior trials:
{json.dumps(history, ensure_ascii=True)}
"""
        payload = await self._generate(
            prompt,
            StrategyCritique.model_json_schema(),
            temperature=0.3,
        )
        return StrategyCritique.model_validate_json(payload)

    async def _generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        temperature: float,
    ) -> str:
        response = await self._client.post(
            "/api/generate",
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {
                    "temperature": temperature,
                    "num_ctx": 16_384,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("response", "")
        if not content:
            raise ValueError("Ollama returned an empty structured response")
        return content
