from dataclasses import dataclass


@dataclass(frozen=True)
class ModeledExecution:
    gross_result_r: float
    exit_reference_price: float
    entry_fill_price: float
    exit_fill_price: float
    fee_cost_r: float
    slippage_cost_r: float
    net_result_r: float


def model_execution(
    *,
    direction: str,
    entry_price: float,
    stop_price: float,
    exit_reference_price: float,
    taker_fee_rate_pct: float,
    slippage_bps: float,
) -> ModeledExecution:
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        raise ValueError("entry and stop must define positive risk")
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")

    slippage_rate = slippage_bps / 10_000
    fee_rate = taker_fee_rate_pct / 100
    if direction == "long":
        entry_fill = entry_price * (1 + slippage_rate)
        exit_fill = exit_reference_price * (1 - slippage_rate)
        gross_result = (exit_reference_price - entry_price) / risk
        after_slippage = (exit_fill - entry_fill) / risk
    else:
        entry_fill = entry_price * (1 - slippage_rate)
        exit_fill = exit_reference_price * (1 + slippage_rate)
        gross_result = (entry_price - exit_reference_price) / risk
        after_slippage = (entry_fill - exit_fill) / risk
    slippage_cost = max(0.0, gross_result - after_slippage)
    fee_cost = fee_rate * (entry_fill + exit_fill) / risk
    return ModeledExecution(
        gross_result_r=round(gross_result, 6),
        exit_reference_price=round(exit_reference_price, 12),
        entry_fill_price=round(entry_fill, 12),
        exit_fill_price=round(exit_fill, 12),
        fee_cost_r=round(fee_cost, 6),
        slippage_cost_r=round(slippage_cost, 6),
        net_result_r=round(after_slippage - fee_cost, 6),
    )
