import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .execution import model_execution
from .journal_models import TargetHit
from .live_models import TradeTarget
from .market_models import Candle


def evaluate_signal_row(
    row: sqlite3.Row,
    candles: list[Candle],
    now: datetime,
    pending_expiry: timedelta,
    active_expiry: timedelta,
) -> dict[str, Any] | None:
    signal_at = _datetime(row["signal_at"])
    entered_at = _optional_datetime(row["entered_at"])
    last_evaluated = _optional_datetime(row["last_evaluated_at"])
    state = row["lifecycle_state"]
    target_hits = [TargetHit.model_validate(item) for item in json.loads(row["target_hits_json"])]
    targets = [TradeTarget.model_validate(item) for item in json.loads(row["targets_json"])]
    mfe_r = float(row["mfe_r"])
    mae_r = float(row["mae_r"])
    changed = False
    outcome = row["outcome"]
    closed_at = _optional_datetime(row["closed_at"])
    result_r = row["result_r"]
    exit_reference_price = row["exit_reference_price"]
    entry_fill_price = row["entry_fill_price"]
    exit_fill_price = row["exit_fill_price"]
    fee_cost_r = row["fee_cost_r"]
    slippage_cost_r = row["slippage_cost_r"]
    net_result_r = row["net_result_r"]

    relevant = sorted(
        (
            candle
            for candle in candles
            if candle.is_closed
            and candle.start_time >= signal_at
            and (last_evaluated is None or candle.start_time > last_evaluated)
        ),
        key=lambda candle: candle.start_time,
    )
    latest_evaluated = last_evaluated
    hit_labels = {hit.label for hit in target_hits}
    policy_target = min(targets, key=lambda target: target.reward_risk) if targets else None

    if net_result_r is None and policy_target is not None and policy_target.label in hit_labels:
        (
            result_r,
            exit_reference_price,
            entry_fill_price,
            exit_fill_price,
            fee_cost_r,
            slippage_cost_r,
            net_result_r,
        ) = _execution_result(row, policy_target.price)
        changed = True

    for candle in relevant:
        latest_evaluated = candle.start_time
        entry_touched = _entry_touched(row, candle)
        stop_touched = _stop_touched(row, candle)
        new_targets = [
            target
            for target in targets
            if target.label not in hit_labels and _target_touched(row, target, candle)
        ]

        if state == "pending_entry":
            if entry_touched and (stop_touched or new_targets):
                state, outcome, closed_at = "closed", "ambiguous", candle.start_time
                entered_at = candle.start_time
                changed = True
                break
            if stop_touched:
                state, outcome, closed_at = (
                    "closed",
                    "invalidated_before_entry",
                    candle.start_time,
                )
                changed = True
                break
            if not entry_touched:
                continue
            state = "active"
            entered_at = candle.start_time
            changed = True

        mfe_r, mae_r = _excursions(row, candle, mfe_r, mae_r)
        if stop_touched and new_targets:
            state, outcome, closed_at = "closed", "ambiguous", candle.start_time
            changed = True
            break
        for target in new_targets:
            target_hits.append(
                TargetHit(
                    label=target.label,
                    price=target.price,
                    reward_risk=target.reward_risk,
                    hit_at=candle.start_time,
                )
            )
            hit_labels.add(target.label)
            changed = True
        if net_result_r is None and policy_target is not None and policy_target.label in hit_labels:
            (
                result_r,
                exit_reference_price,
                entry_fill_price,
                exit_fill_price,
                fee_cost_r,
                slippage_cost_r,
                net_result_r,
            ) = _execution_result(row, policy_target.price)
            changed = True
        if stop_touched:
            state = "closed"
            outcome = "stop_after_target" if target_hits else "stop_before_target"
            if net_result_r is None:
                (
                    result_r,
                    exit_reference_price,
                    entry_fill_price,
                    exit_fill_price,
                    fee_cost_r,
                    slippage_cost_r,
                    net_result_r,
                ) = _execution_result(row, float(row["stop_price"]))
            closed_at = candle.start_time
            changed = True
            break
        if targets and len(hit_labels) == len(targets):
            state = "closed"
            outcome = "target_complete"
            closed_at = candle.start_time
            changed = True
            break

    if state == "pending_entry" and now - signal_at >= pending_expiry:
        state, outcome, closed_at = "closed", "expired_without_entry", now
        changed = True
    elif state == "active" and entered_at is not None and now - entered_at >= active_expiry:
        state, outcome, closed_at = "closed", "expired_active", now
        if net_result_r is None:
            exit_candle = _latest_closed_candle(candles, entered_at, now)
            if exit_candle is not None:
                (
                    result_r,
                    exit_reference_price,
                    entry_fill_price,
                    exit_fill_price,
                    fee_cost_r,
                    slippage_cost_r,
                    net_result_r,
                ) = _execution_result(row, exit_candle.close)
        changed = True

    if latest_evaluated != last_evaluated:
        changed = True
    if not changed:
        return None
    return {
        "id": row["id"],
        "lifecycle_state": state,
        "outcome": outcome,
        "entered_at": _iso(entered_at) if entered_at else None,
        "closed_at": _iso(closed_at) if closed_at else None,
        "target_hits_json": json.dumps(
            [hit.model_dump(mode="json") for hit in target_hits],
            separators=(",", ":"),
        ),
        "mfe_r": round(mfe_r, 6),
        "mae_r": round(mae_r, 6),
        "result_r": result_r,
        "exit_reference_price": exit_reference_price,
        "entry_fill_price": entry_fill_price,
        "exit_fill_price": exit_fill_price,
        "fee_cost_r": fee_cost_r,
        "slippage_cost_r": slippage_cost_r,
        "net_result_r": net_result_r,
        "last_evaluated_at": _iso(latest_evaluated) if latest_evaluated else None,
    }


def _entry_touched(row: sqlite3.Row, candle: Candle) -> bool:
    return candle.low <= row["entry_upper"] and candle.high >= row["entry_lower"]


def _stop_touched(row: sqlite3.Row, candle: Candle) -> bool:
    if row["direction"] == "long":
        return candle.low <= row["stop_price"]
    return candle.high >= row["stop_price"]


def _target_touched(row: sqlite3.Row, target: TradeTarget, candle: Candle) -> bool:
    if row["direction"] == "long":
        return candle.high >= target.price
    return candle.low <= target.price


def _excursions(
    row: sqlite3.Row,
    candle: Candle,
    mfe_r: float,
    mae_r: float,
) -> tuple[float, float]:
    risk = abs(row["entry_price"] - row["stop_price"])
    if not risk:
        return mfe_r, mae_r
    if row["direction"] == "long":
        favorable = max(0.0, (candle.high - row["entry_price"]) / risk)
        adverse = max(0.0, (row["entry_price"] - candle.low) / risk)
    else:
        favorable = max(0.0, (row["entry_price"] - candle.low) / risk)
        adverse = max(0.0, (candle.high - row["entry_price"]) / risk)
    return max(mfe_r, favorable), max(mae_r, adverse)


def _execution_result(
    row: sqlite3.Row,
    exit_reference_price: float,
) -> tuple[float, float, float, float, float, float, float]:
    result = model_execution(
        direction=row["direction"],
        entry_price=float(row["entry_price"]),
        stop_price=float(row["stop_price"]),
        exit_reference_price=exit_reference_price,
        taker_fee_rate_pct=float(row["taker_fee_rate_pct"]),
        slippage_bps=float(row["slippage_bps"]),
    )
    return (
        result.gross_result_r,
        result.exit_reference_price,
        result.entry_fill_price,
        result.exit_fill_price,
        result.fee_cost_r,
        result.slippage_cost_r,
        result.net_result_r,
    )


def _latest_closed_candle(
    candles: list[Candle],
    entered_at: datetime,
    now: datetime,
) -> Candle | None:
    eligible = [
        candle for candle in candles if candle.is_closed and entered_at <= candle.start_time <= now
    ]
    return max(eligible, key=lambda candle: candle.start_time) if eligible else None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None
