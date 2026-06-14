import pytest
from pydantic import ValidationError

from trade3_api.config import Settings


def test_market_allowlist_is_normalized_and_deduplicated() -> None:
    settings = Settings(
        _env_file=None,
        market_allowed_base_coins=" btc,ETH,btc,1000pepe ",
    )

    assert settings.market_allowed_base_coins == "BTC,ETH,1000PEPE"
    assert settings.market_allowed_base_coin_set() == {"BTC", "ETH", "1000PEPE"}


def test_rejected_strategy_journal_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.journal_enabled is False


def test_empty_market_allowlist_disables_core_universe_filter() -> None:
    settings = Settings(_env_file=None, market_allowed_base_coins="")

    assert settings.market_allowed_base_coin_set() is None


def test_market_allowlist_rejects_invalid_identifiers() -> None:
    with pytest.raises(ValidationError, match="invalid base coin"):
        Settings(_env_file=None, market_allowed_base_coins="BTC,ETH/USDT")
