import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .ai_models import (
    AiConviction,
    AiMarketReview,
    AiObservedBiases,
    AiReviewPayload,
    AiReviewStatus,
    AiSummaryCode,
    AiVerdict,
)
from .analysis_models import MarketAnalysisSnapshot
from .flow_models import MarketFlowSnapshot


class OllamaMarketAnalyst:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 90,
        cache_seconds: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama must use a loopback address")
        self._model = model
        self._cache_seconds = cache_seconds
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            trust_env=False,
        )
        self._owns_client = client is None
        self._cache: dict[str, tuple[float, AiMarketReview]] = {}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def review(
        self,
        snapshot: MarketAnalysisSnapshot,
        flow: MarketFlowSnapshot | None = None,
    ) -> AiMarketReview:
        context = _review_context(snapshot, flow)
        cache_key = hashlib.sha256(
            json.dumps(context, ensure_ascii=True, sort_keys=True).encode()
        ).hexdigest()
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] <= self._cache_seconds:
            return cached[1]

        started = time.monotonic()
        # A connection/timeout fault means Ollama is offline, so fail fast. A
        # rejected answer means Ollama is online but a small model produced a
        # fact-inconsistent reply, so retry once before giving up.
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await self._client.post(
                    "/api/generate",
                    json={
                        "model": self._model,
                        "prompt": _review_prompt(context),
                        "stream": False,
                        "think": False,
                        "format": AiReviewPayload.model_json_schema(),
                        "keep_alive": "10m",
                        "options": {
                            "temperature": 0.2,
                            "num_ctx": 8192,
                        },
                    },
                )
                response.raise_for_status()
                content = response.json().get("response", "")
                if not content:
                    raise ValueError("Ollama returned an empty structured response")
                payload = AiReviewPayload.model_validate_json(content)
                _validate_payload(payload, snapshot, context)
            except httpx.HTTPError as exc:
                return _unavailable_review(snapshot, self._model, started, exc)
            except (ValueError, ValidationError) as exc:
                last_error = exc
                continue

            review = _render_review(
                payload=payload,
                snapshot=snapshot,
                flow=flow,
                context=context,
                model=self._model,
                started=started,
            )
            self._cache[cache_key] = (time.monotonic(), review)
            return review

        return _unavailable_review(
            snapshot, self._model, started, last_error or ValueError("rejected")
        )


def _render_review(
    *,
    payload: AiReviewPayload,
    snapshot: MarketAnalysisSnapshot,
    flow: MarketFlowSnapshot | None,
    context: dict[str, Any],
    model: str,
    started: float,
) -> AiMarketReview:
    facts: dict[str, str] = context["available_facts"]
    wait_conditions: dict[str, str] = context["wait_conditions"]
    return AiMarketReview(
        observed_biases=payload.observed_biases,
        verdict=payload.verdict,
        conviction=payload.conviction,
        summary_code=payload.summary_code,
        supporting_fact_ids=payload.supporting_fact_ids,
        counter_fact_ids=payload.counter_fact_ids,
        wait_condition_ids=payload.wait_condition_ids,
        market_flow=flow,
        symbol=snapshot.symbol,
        status=AiReviewStatus.READY,
        model=model,
        generated_at=datetime.now(UTC),
        snapshot_generated_at=snapshot.generated_at,
        runtime_ms=round((time.monotonic() - started) * 1000),
        headline=_headline(payload),
        thesis=_thesis(payload),
        confirmations=[facts[item] for item in payload.supporting_fact_ids],
        counterarguments=[facts[item] for item in payload.counter_fact_ids],
        wait_for=[wait_conditions[item] for item in payload.wait_condition_ids],
        limitations=_limitations(),
    )


def _review_context(
    snapshot: MarketAnalysisSnapshot,
    flow: MarketFlowSnapshot | None,
) -> dict[str, Any]:
    zones = sorted(
        snapshot.zones,
        key=lambda zone: abs((zone.lower + zone.upper) / 2 - snapshot.last_price),
    )[:12]
    context = {
        "symbol": snapshot.symbol,
        "last_price": snapshot.last_price,
        "deterministic_preference": snapshot.preferred_direction,
        "deterministic_decision": snapshot.decision,
        "structures": [
            {
                "timeframe": _timeframe_label(item.timeframe),
                "bias": item.bias,
                "atr": item.atr,
                "latest_events": [
                    {"kind": event.kind, "price": event.price} for event in item.events[:3]
                ],
            }
            for item in snapshot.structures
        ],
        "nearest_zones": [
            {
                "timeframe": _timeframe_label(zone.timeframe),
                "kind": zone.kind,
                "lower": zone.lower,
                "upper": zone.upper,
                "strength": zone.strength,
                "touches": zone.touches,
            }
            for zone in zones
        ],
        "conditional_scenarios": [
            {
                "direction": scenario.direction,
                "status": scenario.status,
                "quality": scenario.quality,
                "entry_zone": scenario.entry_zone.model_dump(),
                "trigger": scenario.trigger,
                "invalidation_price": scenario.invalidation_price,
                "targets": [target.model_dump() for target in scenario.targets],
                "evidence": [_normalize_fact(item) for item in scenario.evidence],
                "conflicts": [_normalize_fact(item) for item in scenario.conflicts],
            }
            for scenario in snapshot.scenarios
        ],
        "market_flow": flow.model_dump(mode="json") if flow else None,
    }
    context["available_facts"] = _available_facts(snapshot, zones, flow)
    context["wait_conditions"] = _wait_conditions(snapshot)
    return context


def _review_prompt(context: dict[str, Any]) -> str:
    return f"""
Ты локальный аналитик фьючерсного intraday-терминала. Исполнение сделок всегда ручное.
Проанализируй только переданный снимок рынка и верни ответ строго по JSON-схеме.

Правила:
- Не придумывай свечи, новости, объёмы, ликвидации, стакан или внешние данные.
- Не создавай и не изменяй цены входа, стопа и целей: они уже рассчитаны отдельно.
- long_candidate/short_candidate означает только условный сценарий после указанного триггера.
- Если таймфреймы конфликтуют или преимущество неясно, выбирай wait.
- Доступны ровно 4ч, 1ч, 15м и 5м. Не упоминай никакие другие таймфреймы.
- В observed_biases дословно перенеси bias из structures: 4h -> h4, 1h -> h1,
  15m -> m15, 5m -> m5. Не интерпретируй и не меняй эти значения.
- conviction означает ясность контекста, а не вероятность выигрыша.
- supporting_fact_ids и counter_fact_ids выбирай только из ключей available_facts.
- wait_condition_ids выбирай только из ключей wait_conditions.
- Не создавай свободный текст: выбери verdict, conviction, summary_code и идентификаторы.

Снимок рынка:
{json.dumps(context, ensure_ascii=False, separators=(",", ":"))}
"""


def _validate_payload(
    payload: AiReviewPayload,
    snapshot: MarketAnalysisSnapshot,
    context: dict[str, Any],
) -> None:
    structures = {item.timeframe: item.bias for item in snapshot.structures}
    expected = {
        "h4": structures.get("240"),
        "h1": structures.get("60"),
        "m15": structures.get("15"),
        "m5": structures.get("5"),
    }
    # The biases only echo the deterministic snapshot, so a small model getting
    # them slightly wrong should not sink the whole review — coerce them to the
    # computed values instead of rejecting the answer.
    if None not in expected.values():
        payload.observed_biases = AiObservedBiases(**expected)

    facts = set(context["available_facts"])
    wait_conditions = set(context["wait_conditions"])
    selected_facts = set(payload.supporting_fact_ids) | set(payload.counter_fact_ids)
    if not selected_facts <= facts:
        raise ValueError(f"Ollama referenced unavailable facts: {sorted(selected_facts - facts)}")
    selected_wait = set(payload.wait_condition_ids)
    if not selected_wait <= wait_conditions:
        raise ValueError(
            f"Ollama referenced unavailable wait conditions: {sorted(selected_wait - wait_conditions)}"
        )
    if set(payload.supporting_fact_ids) & set(payload.counter_fact_ids):
        raise ValueError("Ollama used the same fact as support and counterargument")

    direction = {
        AiVerdict.LONG_CANDIDATE: "long",
        AiVerdict.SHORT_CANDIDATE: "short",
        AiVerdict.WAIT: None,
    }[payload.verdict]
    if direction and not any(item.direction == direction for item in snapshot.scenarios):
        raise ValueError(f"Ollama referenced unavailable {direction} scenario")
    if payload.verdict == AiVerdict.WAIT and not payload.wait_condition_ids:
        payload.wait_condition_ids = ["timeframe_alignment"]
    if payload.verdict == AiVerdict.LONG_CANDIDATE:
        payload.wait_condition_ids = list(
            dict.fromkeys([*payload.wait_condition_ids[:4], "long_trigger"])
        )
    if payload.verdict == AiVerdict.SHORT_CANDIDATE:
        payload.wait_condition_ids = list(
            dict.fromkeys([*payload.wait_condition_ids[:4], "short_trigger"])
        )


def _unavailable_review(
    snapshot: MarketAnalysisSnapshot,
    model: str,
    started: float,
    reason: Exception,
) -> AiMarketReview:
    rejected = not isinstance(reason, httpx.HTTPError)
    status = AiReviewStatus.REJECTED if rejected else AiReviewStatus.UNAVAILABLE
    safe_reason = (
        "Ответ модели не прошёл проверку фактов и был отклонён."
        if rejected
        else "Ollama недоступна или превысила время ожидания."
    )
    headline = (
        "AI-разбор отклонён проверкой фактов"
        if rejected
        else "Локальный AI-разбор временно недоступен"
    )
    return AiMarketReview(
        symbol=snapshot.symbol,
        status=status,
        model=model,
        generated_at=datetime.now(UTC),
        snapshot_generated_at=snapshot.generated_at,
        runtime_ms=round((time.monotonic() - started) * 1000),
        market_flow=None,
        observed_biases={
            "h4": next(item.bias for item in snapshot.structures if item.timeframe == "240"),
            "h1": next(item.bias for item in snapshot.structures if item.timeframe == "60"),
            "m15": next(item.bias for item in snapshot.structures if item.timeframe == "15"),
            "m5": next(item.bias for item in snapshot.structures if item.timeframe == "5"),
        },
        verdict=AiVerdict.WAIT,
        conviction=AiConviction.LOW,
        summary_code=AiSummaryCode.NO_EDGE,
        supporting_fact_ids=[],
        counter_fact_ids=[],
        wait_condition_ids=["retry_ai"],
        headline=headline,
        thesis="Используйте только карту рынка и ручной чек-лист, пока Ollama не вернёт валидный разбор.",
        confirmations=[],
        counterarguments=[safe_reason] if safe_reason else [],
        wait_for=["Дождаться доступности локальной модели и повторить анализ."],
        limitations=_limitations(),
    )


def _timeframe_label(timeframe: str) -> str:
    return {
        "240": "4h",
        "60": "1h",
        "15": "15m",
        "5": "5m",
    }.get(timeframe, timeframe)


def _normalize_fact(value: str) -> str:
    for raw, label in (("240", "4h"), ("60", "1h"), ("15", "15m"), ("5", "5m")):
        if value.startswith(f"{raw} "):
            return f"{label} {value[len(raw) + 1 :]}"
        value = value.replace(f"references {raw} ", f"references {label} ")
    return value


def _available_facts(
    snapshot: MarketAnalysisSnapshot,
    zones: list,
    flow: MarketFlowSnapshot | None,
) -> dict[str, str]:
    facts: dict[str, str] = {}
    bias_labels = {
        "bullish": "восходящая",
        "bearish": "нисходящая",
        "range": "диапазон",
        "insufficient": "недостаточно данных",
    }
    zone_labels = {
        "support": "поддержка",
        "resistance": "сопротивление",
        "bullish_fvg": "бычий FVG",
        "bearish_fvg": "медвежий FVG",
        "bullish_order_block": "бычий order block",
        "bearish_order_block": "медвежий order block",
        "liquidity_high": "ликвидность сверху",
        "liquidity_low": "ликвидность снизу",
    }
    for structure in snapshot.structures:
        timeframe = _timeframe_label(structure.timeframe)
        facts[f"structure_{timeframe}_{structure.bias}"] = (
            f"{timeframe}: структура {bias_labels[structure.bias]}."
        )
        for event in structure.events[:2]:
            event_label = {
                "bos_up": "свежий BOS вверх",
                "bos_down": "свежий BOS вниз",
                "choch_up": "свежий CHOCH вверх",
                "choch_down": "свежий CHOCH вниз",
            }.get(event.kind, event.kind)
            facts[f"event_{timeframe}_{event.kind}"] = f"{timeframe}: {event_label}."
    for index, zone in enumerate(zones[:8]):
        timeframe = _timeframe_label(zone.timeframe)
        facts[f"zone_{index}"] = (
            f"Рядом с ценой есть зона «{zone_labels[zone.kind]}» на {timeframe}."
        )
    for scenario in snapshot.scenarios:
        direction = scenario.direction
        quality = {
            "low": "слабое",
            "medium": "среднее",
            "high": "сильное",
        }.get(scenario.quality, scenario.quality)
        facts[f"{direction}_quality_{scenario.quality}"] = (
            f"Условный {direction.upper()}-сценарий имеет {quality} качество."
        )
        if any(target.reward_risk >= 1.5 for target in scenario.targets):
            facts[f"{direction}_target_1_5r"] = (
                f"У условного {direction.upper()}-сценария есть цель не ниже 1.5R."
            )
    if flow:
        for band in flow.orderbook_bands:
            if band.imbalance > 0.1:
                side = "bid"
                description = f"В стакане до {band.distance_bps} bps преобладает bid-ликвидность."
            elif band.imbalance < -0.1:
                side = "ask"
                description = f"В стакане до {band.distance_bps} bps преобладает ask-ликвидность."
            else:
                side = "balanced"
                description = f"Стакан до {band.distance_bps} bps близок к балансу."
            if not band.depth_complete:
                description += " Доступная глубина не покрывает весь диапазон."
            facts[f"orderbook_{band.distance_bps}bps_{side}"] = description

        trade_flow = flow.trade_flow
        if trade_flow.imbalance > 0.1:
            trade_side = "buy"
            trade_description = "За последнюю минуту преобладали агрессивные покупки."
        elif trade_flow.imbalance < -0.1:
            trade_side = "sell"
            trade_description = "За последнюю минуту преобладали агрессивные продажи."
        else:
            trade_side = "balanced"
            trade_description = "Поток агрессивных сделок за минуту близок к балансу."
        if trade_flow.sample_truncated:
            trade_description += " Выборка достигла лимита последних 500 сделок."
        facts[f"trade_flow_60s_{trade_side}"] = trade_description

        liquidation = next(
            (item for item in flow.liquidations if item.window_minutes == 15),
            None,
        )
        if liquidation:
            if liquidation.event_count == 0:
                facts["liquidations_15m_none"] = (
                    "За 15 минут в подключённом потоке нет ликвидаций по символу."
                )
            elif liquidation.imbalance > 0.1:
                facts["liquidations_15m_shorts"] = (
                    "За 15 минут преобладали ликвидации коротких позиций."
                )
            elif liquidation.imbalance < -0.1:
                facts["liquidations_15m_longs"] = (
                    "За 15 минут преобладали ликвидации длинных позиций."
                )
            else:
                facts["liquidations_15m_balanced"] = (
                    "Ликвидации длинных и коротких позиций за 15 минут близки к балансу."
                )
    return facts


def _wait_conditions(snapshot: MarketAnalysisSnapshot) -> dict[str, str]:
    conditions = {
        "timeframe_alignment": "Дождаться согласования структуры 1h и 15m.",
        "orderflow_check": "Проверить подтверждение в стакане или дельте объёма.",
        "liquidation_heatmap_check": "Проверить ближайшие кластеры на карте ликвидаций.",
        "news_check": "Проверить новости и календарь событий перед входом.",
        "retry_ai": "Повторить локальный AI-анализ на свежем снимке.",
    }
    for scenario in snapshot.scenarios:
        conditions[f"{scenario.direction}_trigger"] = (
            "Дождаться реакции в рассчитанной зоне и подтверждающего закрытия 5m "
            + ("выше неё." if scenario.direction == "long" else "ниже неё.")
        )
    return conditions


def _headline(payload: AiReviewPayload) -> str:
    if payload.verdict == AiVerdict.LONG_CANDIDATE:
        return "Лонг остаётся условным кандидатом после подтверждения"
    if payload.verdict == AiVerdict.SHORT_CANDIDATE:
        return "Шорт остаётся условным кандидатом после подтверждения"
    return {
        AiSummaryCode.MIXED_CONTEXT: "Таймфреймы конфликтуют: сейчас лучше ждать",
        AiSummaryCode.RANGE_CONTEXT: "Рынок в диапазоне: направленного преимущества нет",
        AiSummaryCode.TRIGGER_PENDING: "Контекст есть, но триггер входа ещё не получен",
        AiSummaryCode.NO_EDGE: "Подтверждённого преимущества сейчас нет",
        AiSummaryCode.ALIGNED_LONG: "Лонг-контекст требует ручного подтверждения",
        AiSummaryCode.ALIGNED_SHORT: "Шорт-контекст требует ручного подтверждения",
    }[payload.summary_code]


def _thesis(payload: AiReviewPayload) -> str:
    direction = {
        AiVerdict.LONG_CANDIDATE: "условный лонг",
        AiVerdict.SHORT_CANDIDATE: "условный шорт",
        AiVerdict.WAIT: "ожидание",
    }[payload.verdict]
    clarity = {
        AiConviction.LOW: "низкая",
        AiConviction.MEDIUM: "средняя",
        AiConviction.HIGH: "высокая",
    }[payload.conviction]
    return (
        f"Модель выбрала: {direction}. Ясность контекста: {clarity}. "
        "Все уровни берутся только из рассчитанной карты рынка; решение о входе остаётся ручным."
    )


def _limitations() -> list[str]:
    return [
        "Стакан является моментальным REST-снимком и не включает RPI-заявки.",
        "Поток ликвидаций начинается после запуска локального терминала.",
        "AI пока не видит новости и внешнюю агрегированную карту ликвидаций.",
        "AI не меняет рассчитанные уровни и не размещает ордера.",
        "Качественная conviction не является вероятностью выигрыша.",
    ]
